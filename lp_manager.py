"""
LP Manager - Buka dan tutup posisi LP di Meteora DLMM (REAL TRANSACTIONS)
Menggunakan meteora_client + tx_builder + token_helper untuk transaksi on-chain
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from config import BotConfig
from pool_scanner import PoolInfo
from meteora_client import MeteoraRPC
from tx_builder import (
    SolanaTransactionBuilder,
    get_associated_token_address,
    derive_position_pda,
    find_pda,
)
from token_helper import (
    token_account_exists,
    lamports_to_sol,
    build_wrap_sol_instructions,
    build_close_wsol_instruction,
    calculate_amounts_for_spot,
    WSOL_MINT,
)

logger = logging.getLogger(__name__)

METEORA_PROGRAM  = "LBUZKhRxPF3XUpBCjp4YzTKgLLjZAd7CKzFQAAAAA"
DEFAULT_BIN_SPREAD = 34


@dataclass
class Position:
    pool_address: str
    pool_name: str
    sol_deployed: float
    position_pda: str = ""
    lower_bin_id: int = 0
    upper_bin_id: int = 0
    opened_at: float = field(default_factory=time.time)
    fees_earned_sol: float = 0.0
    is_in_range: bool = True
    out_of_range_since: Optional[float] = None
    tx_signature: str = ""

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.opened_at) / 60

    @property
    def out_of_range_minutes(self) -> float:
        if self.out_of_range_since is None:
            return 0
        return (time.time() - self.out_of_range_since) / 60

    @property
    def fee_return_pct(self) -> float:
        if self.sol_deployed == 0:
            return 0
        return (self.fees_earned_sol / self.sol_deployed) * 100

    def to_dict(self) -> dict:
        return {
            "pool_address": self.pool_address,
            "pool_name": self.pool_name,
            "sol_deployed": self.sol_deployed,
            "position_pda": self.position_pda,
            "age_minutes": round(self.age_minutes, 1),
            "fees_earned_sol": self.fees_earned_sol,
            "fee_return_pct": round(self.fee_return_pct, 2),
            "is_in_range": self.is_in_range,
            "out_of_range_minutes": round(self.out_of_range_minutes, 1),
        }


class LPManager:
    def __init__(self, config: BotConfig):
        self.config = config
        self.positions: Dict[str, Position] = {}
        self._wallet = None
        self._owner_str = ""
        self._rpc = MeteoraRPC(config.rpc_url)
        self._tx = SolanaTransactionBuilder(config.rpc_url, METEORA_PROGRAM)
        self._simulation_mode = True
        self._init_wallet()

    def _init_wallet(self):
        if not self.config.wallet_private_key:
            logger.warning("⚠️  Wallet key tidak diset - mode SIMULASI aktif")
            return
        try:
            from solders.keypair import Keypair
            import base58
            self._wallet = Keypair.from_bytes(base58.b58decode(self.config.wallet_private_key))
            self._owner_str = str(self._wallet.pubkey())
            self._simulation_mode = False
            logger.info(f"✅ Wallet: {self._owner_str[:8]}...{self._owner_str[-4:]}")
        except ImportError:
            logger.error("❌ Jalankan: pip install solders base58")
        except Exception as e:
            logger.error(f"❌ Wallet error: {e}")

    @property
    def active_position_count(self) -> int:
        return len(self.positions)

    @property
    def total_sol_deployed(self) -> float:
        return sum(p.sol_deployed for p in self.positions.values())

    async def get_sol_balance(self) -> float:
        if self._simulation_mode:
            return 999.0
        try:
            lamports = await self._rpc.get_balance(self._owner_str)
            return lamports_to_sol(lamports)
        except Exception as e:
            logger.error(f"Balance error: {e}")
            return 0.0

    # =========================================================
    # OPEN POSITION
    # =========================================================

    async def open_position(self, pool: PoolInfo) -> Optional[Position]:
        cfg = self.config
        if self.active_position_count >= cfg.max_concurrent_positions:
            logger.info(f"⛔ Max posisi ({cfg.max_concurrent_positions})")
            return None
        if pool.address in self.positions:
            return None

        balance = await self.get_sol_balance()
        if balance < cfg.min_sol_balance + cfg.sol_per_position:
            logger.warning(f"⛔ Balance kurang: {balance:.3f} SOL")
            return None

        sol_amount = min(cfg.sol_per_position, cfg.max_sol_per_position)

        if self._simulation_mode:
            return await self._open_simulated(pool, sol_amount)
        return await self._open_real(pool, sol_amount)

    async def _open_simulated(self, pool: PoolInfo, sol_amount: float) -> Position:
        logger.info(f"📝 [SIMULASI] Buka {pool.name} | {sol_amount} SOL")
        pos = Position(
            pool_address=pool.address, pool_name=pool.name,
            sol_deployed=sol_amount,
            tx_signature=f"SIM_{pool.address[:8]}_{int(time.time())}",
        )
        self.positions[pool.address] = pos
        return pos

    async def _open_real(self, pool: PoolInfo, sol_amount: float) -> Optional[Position]:
        logger.info(f"💸 Buka posisi nyata: {pool.name} | {sol_amount} SOL")
        try:
            # 1. Ambil state pool
            pool_state = await self._rpc.get_pool_state(pool.address)
            if not pool_state:
                logger.error("Gagal ambil pool state")
                return None

            # 2. Bin range
            active_bin = pool_state.active_bin_id
            lower_bin  = active_bin - DEFAULT_BIN_SPREAD
            upper_bin  = active_bin + DEFAULT_BIN_SPREAD

            # 3. Position PDA
            position_pda, _ = derive_position_pda(
                pool.address, self._owner_str,
                lower_bin, upper_bin, METEORA_PROGRAM
            )

            # 4. Token info
            mint_x = pool_state.token_x_mint
            mint_y = pool_state.token_y_mint
            token_x_is_sol = (mint_x == WSOL_MINT)

            # 5. Hitung amounts (50/50 Spot strategy)
            amount_x, amount_y = calculate_amounts_for_spot(
                sol_amount, pool_state.price, token_x_is_sol
            )

            # 6. ATA addresses
            ata_x = get_associated_token_address(self._owner_str, mint_x)
            ata_y = get_associated_token_address(self._owner_str, mint_y)

            # 7. Reserve PDAs
            reserve_x, _ = find_pda(
                [b"reserve",
                 bytes(__import__("solders.pubkey", fromlist=["Pubkey"]).Pubkey.from_string(pool.address)),
                 bytes(__import__("solders.pubkey", fromlist=["Pubkey"]).Pubkey.from_string(mint_x))],
                METEORA_PROGRAM
            )
            reserve_y, _ = find_pda(
                [b"reserve",
                 bytes(__import__("solders.pubkey", fromlist=["Pubkey"]).Pubkey.from_string(pool.address)),
                 bytes(__import__("solders.pubkey", fromlist=["Pubkey"]).Pubkey.from_string(mint_y))],
                METEORA_PROGRAM
            )

            # 8. Build instruksi
            ixs = []

            # Buat ATA jika belum ada
            for ata, mint in [(ata_x, mint_x), (ata_y, mint_y)]:
                if not await token_account_exists(self.config.rpc_url, ata):
                    ixs.append(await self._tx.build_create_ata_ix(self._owner_str, mint, self._owner_str))

            # Wrap SOL jika perlu
            if token_x_is_sol and amount_x > 0:
                ixs.extend(build_wrap_sol_instructions(self._owner_str, ata_x, amount_x))
            elif (mint_y == WSOL_MINT) and amount_y > 0:
                ixs.extend(build_wrap_sol_instructions(self._owner_str, ata_y, amount_y))

            # Initialize position
            ixs.append(await self._tx.build_initialize_position_ix(
                pool.address, position_pda, self._owner_str, lower_bin, upper_bin
            ))

            # Add liquidity
            ixs.append(await self._tx.build_add_liquidity_ix(
                lb_pair=pool.address, position_pda=position_pda, owner=self._owner_str,
                user_token_x=ata_x, user_token_y=ata_y,
                reserve_x=reserve_x, reserve_y=reserve_y,
                token_x_mint=mint_x, token_y_mint=mint_y,
                amount_x=amount_x, amount_y=amount_y,
                lower_bin_id=lower_bin, upper_bin_id=upper_bin,
            ))

            # 9. Sign & send
            blockhash, _ = await self._rpc.get_latest_blockhash()
            signed = self._tx.build_and_sign_transaction(ixs, self._wallet, blockhash)
            tx_sig = await self._rpc.send_transaction(signed)
            logger.info(f"📤 TX: {tx_sig}")

            if not await self._rpc.confirm_transaction(tx_sig):
                logger.error("❌ TX gagal dikonfirmasi")
                return None

            pos = Position(
                pool_address=pool.address, pool_name=pool.name,
                sol_deployed=sol_amount, position_pda=position_pda,
                lower_bin_id=lower_bin, upper_bin_id=upper_bin,
                tx_signature=tx_sig,
            )
            self.positions[pool.address] = pos
            logger.info(f"✅ Posisi dibuka! https://solscan.io/tx/{tx_sig}")
            return pos

        except Exception as e:
            logger.error(f"❌ Open error: {e}", exc_info=True)
            return None

    # =========================================================
    # CLOSE POSITION
    # =========================================================

    async def close_position(self, pool_address: str, reason: str = "") -> bool:
        position = self.positions.get(pool_address)
        if not position:
            return False

        logger.info(f"🔄 Tutup posisi {position.pool_name} | {reason}")

        if self._simulation_mode:
            logger.info(f"📝 [SIMULASI] Fee earned: {position.fees_earned_sol:.4f} SOL ({position.fee_return_pct:.1f}%)")
        else:
            if not await self._close_real(position):
                return False

        del self.positions[pool_address]
        return True

    async def _close_real(self, position: Position) -> bool:
        if not position.position_pda:
            logger.error("Position PDA kosong")
            return False
        try:
            from solders.pubkey import Pubkey
            pool_state = await self._rpc.get_pool_state(position.pool_address)
            if not pool_state:
                return False

            mint_x = pool_state.token_x_mint
            mint_y = pool_state.token_y_mint
            ata_x  = get_associated_token_address(self._owner_str, mint_x)
            ata_y  = get_associated_token_address(self._owner_str, mint_y)

            reserve_x, _ = find_pda(
                [b"reserve", bytes(Pubkey.from_string(position.pool_address)), bytes(Pubkey.from_string(mint_x))],
                METEORA_PROGRAM
            )
            reserve_y, _ = find_pda(
                [b"reserve", bytes(Pubkey.from_string(position.pool_address)), bytes(Pubkey.from_string(mint_y))],
                METEORA_PROGRAM
            )

            ixs = []

            # 1. Claim fee
            ixs.append(await self._tx.build_claim_fee_ix(
                lb_pair=position.pool_address, position_pda=position.position_pda,
                owner=self._owner_str, user_token_x=ata_x, user_token_y=ata_y,
                reserve_x=reserve_x, reserve_y=reserve_y,
                token_x_mint=mint_x, token_y_mint=mint_y,
            ))

            # 2. Remove liquidity (batasi 20 bin / tx)
            bin_removals = [
                (bid, 10000)
                for bid in range(position.lower_bin_id, position.upper_bin_id + 1)
            ][:20]
            ixs.append(await self._tx.build_remove_liquidity_ix(
                lb_pair=position.pool_address, position_pda=position.position_pda,
                owner=self._owner_str, user_token_x=ata_x, user_token_y=ata_y,
                reserve_x=reserve_x, reserve_y=reserve_y,
                token_x_mint=mint_x, token_y_mint=mint_y,
                bin_liquidity_removal=bin_removals,
            ))

            # 3. Close position (reclaim rent)
            ixs.append(await self._tx.build_close_position_ix(
                position_pda=position.position_pda, lb_pair=position.pool_address,
                owner=self._owner_str, rent_receiver=self._owner_str,
            ))

            # 4. Unwrap wSOL
            wsol_ata = get_associated_token_address(self._owner_str, WSOL_MINT)
            if await token_account_exists(self.config.rpc_url, wsol_ata):
                ixs.append(build_close_wsol_instruction(self._owner_str, wsol_ata))

            # 5. Sign & send
            blockhash, _ = await self._rpc.get_latest_blockhash()
            signed = self._tx.build_and_sign_transaction(ixs, self._wallet, blockhash)
            tx_sig = await self._rpc.send_transaction(signed)
            logger.info(f"📤 Close TX: {tx_sig}")

            confirmed = await self._rpc.confirm_transaction(tx_sig)
            if confirmed:
                logger.info(f"✅ Ditutup! https://solscan.io/tx/{tx_sig}")
            return confirmed

        except Exception as e:
            logger.error(f"❌ Close error: {e}", exc_info=True)
            return False

    # =========================================================
    # MONITORING
    # =========================================================

    async def update_fees_and_range(self, pool_address: str):
        """Refresh fee earned dan status in-range dari on-chain"""
        position = self.positions.get(pool_address)
        if not position or self._simulation_mode:
            return
        try:
            if position.position_pda:
                fee_x, fee_y = await self._rpc.get_fee_earned(position.position_pda)
                pool_state = await self._rpc.get_pool_state(pool_address)
                if pool_state:
                    sol_fee = lamports_to_sol(int(fee_x if pool_state.token_x_mint == WSOL_MINT else fee_y))
                    position.fees_earned_sol = sol_fee
                    in_range = position.lower_bin_id <= pool_state.active_bin_id <= position.upper_bin_id
                    self.mark_out_of_range(pool_address, in_range)
        except Exception as e:
            logger.warning(f"Update fees error: {e}")

    def update_position_fees(self, pool_address: str, fees_sol: float):
        if pool_address in self.positions:
            self.positions[pool_address].fees_earned_sol = fees_sol

    def mark_out_of_range(self, pool_address: str, in_range: bool):
        if pool_address in self.positions:
            pos = self.positions[pool_address]
            if not in_range and pos.is_in_range:
                pos.is_in_range = False
                pos.out_of_range_since = time.time()
                logger.warning(f"⚠️  {pos.pool_name} OOR!")
            elif in_range and not pos.is_in_range:
                pos.is_in_range = True
                pos.out_of_range_since = None
                logger.info(f"✅ {pos.pool_name} kembali in-range")

    def check_exit_conditions(self, position: Position) -> Optional[str]:
        cfg = self.config
        if position.fee_return_pct >= cfg.take_profit_pct:
            return f"Take profit: {position.fee_return_pct:.1f}% >= {cfg.take_profit_pct}%"
        if not position.is_in_range and position.out_of_range_minutes >= cfg.out_of_range_minutes:
            return f"OOR {position.out_of_range_minutes:.0f} mnt >= {cfg.out_of_range_minutes} mnt"
        return None
