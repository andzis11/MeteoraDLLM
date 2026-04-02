"""
Token Helper - Utilitas untuk token Solana:
- Wrap SOL ke wSOL
- Cek/buat Associated Token Account
- Ambil decimals token
- Konversi amount
"""

import aiohttp
import logging
import struct
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

WSOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022    = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SYSTEM_PROGRAM = "11111111111111111111111111111111"


async def get_token_decimals(rpc_url: str, mint: str) -> int:
    """Ambil decimals dari token mint"""
    if mint == WSOL_MINT:
        return 9  # SOL selalu 9 decimals

    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getAccountInfo",
            "params": [mint, {"encoding": "jsonParsed"}]
        }
        async with session.post(rpc_url, json=payload) as resp:
            data = await resp.json()
            info = data.get("result", {}).get("value", {})
            if not info:
                return 6  # default
            parsed = info.get("data", {}).get("parsed", {})
            return parsed.get("info", {}).get("decimals", 6)


async def get_token_balance(rpc_url: str, token_account: str) -> int:
    """Ambil balance token account dalam smallest unit"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountBalance",
            "params": [token_account]
        }
        async with session.post(rpc_url, json=payload) as resp:
            data = await resp.json()
            result = data.get("result", {}).get("value", {})
            return int(result.get("amount", 0))


async def token_account_exists(rpc_url: str, ata: str) -> bool:
    """Cek apakah token account sudah ada"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getAccountInfo",
            "params": [ata, {"encoding": "base64"}]
        }
        async with session.post(rpc_url, json=payload) as resp:
            data = await resp.json()
            return data.get("result", {}).get("value") is not None


def sol_to_lamports(sol: float) -> int:
    return int(sol * 1_000_000_000)


def lamports_to_sol(lamports: int) -> float:
    return lamports / 1_000_000_000


def amount_to_ui(amount: int, decimals: int) -> float:
    return amount / (10 ** decimals)


def ui_to_amount(ui: float, decimals: int) -> int:
    return int(ui * (10 ** decimals))


def build_wrap_sol_instructions(owner: str, wsol_ata: str, lamports: int) -> list:
    """
    Bangun instruksi untuk wrap SOL ke wSOL:
    1. Transfer SOL ke wSOL ATA
    2. SyncNative untuk update balance
    """
    from solders.instruction import Instruction, AccountMeta
    from solders.pubkey import Pubkey

    TOKEN_PROG = Pubkey.from_string(TOKEN_PROGRAM)
    owner_pk   = Pubkey.from_string(owner)
    ata_pk     = Pubkey.from_string(wsol_ata)
    sys_prog   = Pubkey.from_string(SYSTEM_PROGRAM)

    # 1. System transfer SOL ke wSOL ATA
    transfer_data = struct.pack("<IQ", 2, lamports)  # instruction index 2 = Transfer
    transfer_ix = Instruction(
        program_id=sys_prog,
        accounts=[
            AccountMeta(owner_pk, True, True),
            AccountMeta(ata_pk, False, True),
        ],
        data=transfer_data,
    )

    # 2. SyncNative (instruction index 17)
    sync_ix = Instruction(
        program_id=TOKEN_PROG,
        accounts=[AccountMeta(ata_pk, False, True)],
        data=bytes([17]),
    )

    return [transfer_ix, sync_ix]


def build_close_wsol_instruction(owner: str, wsol_ata: str) -> object:
    """
    Bangun instruksi untuk unwrap wSOL kembali ke SOL (closeAccount).
    Instruction index 9 = CloseAccount
    """
    from solders.instruction import Instruction, AccountMeta
    from solders.pubkey import Pubkey

    TOKEN_PROG = Pubkey.from_string(TOKEN_PROGRAM)
    owner_pk   = Pubkey.from_string(owner)
    ata_pk     = Pubkey.from_string(wsol_ata)

    return Instruction(
        program_id=TOKEN_PROG,
        accounts=[
            AccountMeta(ata_pk,   False, True),
            AccountMeta(owner_pk, False, True),   # destination (terima SOL)
            AccountMeta(owner_pk, True,  False),  # authority
        ],
        data=bytes([9]),  # CloseAccount
    )


def calculate_amounts_for_spot(
    sol_amount: float,
    pool_price: float,
    token_x_is_sol: bool,
) -> Tuple[int, int]:
    """
    Hitung amount token X dan Y untuk strategy Spot.
    Spot strategy: 50% di bawah active bin (token Y), 50% di atas (token X).
    Jika token X adalah SOL, kita split 50/50.
    """
    lamports = sol_to_lamports(sol_amount)
    half = lamports // 2

    if token_x_is_sol:
        amount_x = half          # SOL (wSOL)
        amount_y = int(half * pool_price)  # token lain
    else:
        amount_y = half          # SOL (wSOL)
        amount_x = int(half / pool_price) if pool_price > 0 else 0

    return amount_x, amount_y
