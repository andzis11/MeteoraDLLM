"""
Meteora DLMM Client - Interaksi langsung dengan smart contract Meteora di Solana
Menggunakan solders + anchorpy untuk komunikasi dengan program on-chain
"""

import asyncio
import aiohttp
import logging
import struct
import json
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# === METEORA PROGRAM IDs ===
DLMM_PROGRAM_ID    = "LBUZKhRxPF3XUpBCjp4YzTKgLLjTargetIdAAAAAAAA"
DLMM_PROGRAM_ID_V2 = "LBUZKhRxPF3XUpBCjp4YzTKgLLjZAd7CKzFQAAAAA"

# Gunakan program ID resmi Meteora
METEORA_DLMM_PROGRAM = "LBUZKhRxPF3XUpBCjp4YzTKgLLjZAd7CKzFQAAAAA"

# Token Program
TOKEN_PROGRAM_ID        = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID   = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe8bv"
SYSTEM_PROGRAM_ID       = "11111111111111111111111111111111"
SYSVAR_RENT             = "SysvarRent111111111111111111111111111111111"

# Meteora API
METEORA_API_BASE = "https://dlmm-api.meteora.ag"


@dataclass
class DLMMPoolState:
    """State dari DLMM pool on-chain"""
    address: str
    token_x_mint: str
    token_y_mint: str
    active_bin_id: int
    bin_step: int
    fee_rate: int          # dalam basis points
    token_x_reserve: int   # dalam lamports/smallest unit
    token_y_reserve: int
    price: float           # harga token X dalam token Y
    min_bin_id: int
    max_bin_id: int


@dataclass 
class BinRange:
    """Range bin untuk posisi LP"""
    lower_bin_id: int
    upper_bin_id: int
    active_bin_id: int

    @property
    def width(self) -> int:
        return self.upper_bin_id - self.lower_bin_id + 1


class MeteoraRPC:
    """
    Client untuk berinteraksi dengan Meteora DLMM melalui RPC Solana dan Meteora API.
    Semua transaksi dibangun secara manual menggunakan instruction data dari SDK.
    """

    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # =========================================================
    # RPC HELPERS
    # =========================================================

    async def rpc_call(self, method: str, params: list) -> Any:
        """Generic Solana JSON-RPC call"""
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        try:
            async with session.post(
                self.rpc_url, json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                if "error" in data:
                    raise Exception(f"RPC Error: {data['error']}")
                return data.get("result")
        except Exception as e:
            logger.error(f"RPC call {method} failed: {e}")
            raise

    async def get_balance(self, pubkey: str) -> int:
        """Ambil balance SOL dalam lamports"""
        result = await self.rpc_call("getBalance", [pubkey, {"commitment": "confirmed"}])
        return result["value"]

    async def get_latest_blockhash(self) -> Tuple[str, int]:
        """Ambil blockhash terbaru untuk transaksi"""
        result = await self.rpc_call("getLatestBlockhash", [{"commitment": "confirmed"}])
        bh = result["value"]
        return bh["blockhash"], bh["lastValidBlockHeight"]

    async def get_account_info(self, pubkey: str) -> Optional[dict]:
        """Ambil info account Solana"""
        result = await self.rpc_call("getAccountInfo", [
            pubkey,
            {"encoding": "base64", "commitment": "confirmed"}
        ])
        return result.get("value")

    async def send_transaction(self, signed_tx_b64: str) -> str:
        """Kirim transaksi yang sudah disign"""
        result = await self.rpc_call("sendTransaction", [
            signed_tx_b64,
            {
                "encoding": "base64",
                "skipPreflight": False,
                "preflightCommitment": "confirmed",
                "maxRetries": 3,
            }
        ])
        return result  # signature

    async def confirm_transaction(self, signature: str, timeout: int = 60) -> bool:
        """Tunggu konfirmasi transaksi"""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                result = await self.rpc_call("getSignatureStatuses", [
                    [signature],
                    {"searchTransactionHistory": True}
                ])
                statuses = result.get("value", [None])
                status = statuses[0] if statuses else None
                if status:
                    if status.get("err"):
                        logger.error(f"TX failed: {status['err']}")
                        return False
                    conf = status.get("confirmationStatus", "")
                    if conf in ("confirmed", "finalized"):
                        return True
            except Exception as e:
                logger.warning(f"Confirm check error: {e}")
            await asyncio.sleep(2)
        logger.error(f"TX confirmation timeout: {signature}")
        return False

    # =========================================================
    # METEORA API HELPERS
    # =========================================================

    async def get_pool_state(self, pool_address: str) -> Optional[DLMMPoolState]:
        """Ambil state pool dari Meteora API"""
        session = await self._get_session()
        try:
            async with session.get(
                f"{METEORA_API_BASE}/pair/{pool_address}",
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

                return DLMMPoolState(
                    address=pool_address,
                    token_x_mint=data.get("mint_x", ""),
                    token_y_mint=data.get("mint_y", ""),
                    active_bin_id=int(data.get("active_bin_id", 0)),
                    bin_step=int(data.get("bin_step", 10)),
                    fee_rate=int(float(data.get("base_fee_percentage", 1)) * 100),
                    token_x_reserve=int(data.get("reserve_x", 0)),
                    token_y_reserve=int(data.get("reserve_y", 0)),
                    price=float(data.get("current_price", 0)),
                    min_bin_id=int(data.get("active_bin_id", 0)) - 34,
                    max_bin_id=int(data.get("active_bin_id", 0)) + 34,
                )
        except Exception as e:
            logger.error(f"Error fetching pool state {pool_address}: {e}")
            return None

    async def get_active_bin(self, pool_address: str) -> Optional[int]:
        """Ambil active bin ID dari pool"""
        state = await self.get_pool_state(pool_address)
        return state.active_bin_id if state else None

    async def get_position_by_owner(self, pool_address: str, owner: str) -> Optional[dict]:
        """Cari posisi LP milik owner di pool tertentu"""
        session = await self._get_session()
        try:
            async with session.get(
                f"{METEORA_API_BASE}/position/owner/{owner}",
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return None
                positions = await resp.json()
                for pos in positions:
                    if pos.get("lb_pair") == pool_address:
                        return pos
                return None
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return None

    async def get_fee_earned(self, position_address: str) -> Tuple[float, float]:
        """Ambil fee yang sudah earned dari posisi (token_x, token_y)"""
        session = await self._get_session()
        try:
            async with session.get(
                f"{METEORA_API_BASE}/position/{position_address}",
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return 0.0, 0.0
                data = await resp.json()
                fee_x = float(data.get("fee_x_pending", 0))
                fee_y = float(data.get("fee_y_pending", 0))
                return fee_x, fee_y
        except Exception as e:
            logger.error(f"Error fetching fees: {e}")
            return 0.0, 0.0

    def calculate_bin_range(self, active_bin_id: int, spread_bps: int = 200) -> BinRange:
        """
        Hitung range bin untuk posisi LP.
        spread_bps: spread dalam basis points (200 = ±2%)
        """
        half_spread = spread_bps // 2
        lower = active_bin_id - half_spread
        upper = active_bin_id + half_spread
        return BinRange(lower_bin_id=lower, upper_bin_id=upper, active_bin_id=active_bin_id)
