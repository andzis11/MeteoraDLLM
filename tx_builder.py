"""
Transaction Builder - Bangun dan sign transaksi Solana untuk Meteora DLMM
Menggunakan solders untuk serialisasi transaksi
"""

import base64
import logging
import struct
import hashlib
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# ANCHOR DISCRIMINATOR HELPER
# ============================================================

def get_discriminator(namespace: str, name: str) -> bytes:
    """
    Hitung 8-byte Anchor discriminator.
    Format: sha256("<namespace>:<name>")[0:8]
    """
    preimage = f"{namespace}:{name}"
    digest = hashlib.sha256(preimage.encode()).digest()
    return digest[:8]

# Discriminators untuk instruksi Meteora DLMM
DISC_INITIALIZE_POSITION  = get_discriminator("global", "initialize_position")
DISC_ADD_LIQUIDITY_BY_STRATEGY = get_discriminator("global", "add_liquidity_by_strategy")
DISC_REMOVE_LIQUIDITY     = get_discriminator("global", "remove_all_liquidity")
DISC_CLAIM_FEE            = get_discriminator("global", "claim_fee")
DISC_CLOSE_POSITION       = get_discriminator("global", "close_position")


# ============================================================
# SOLANA KEY & PDA HELPERS
# ============================================================

def find_pda(seeds: List[bytes], program_id_str: str) -> Tuple[str, int]:
    """
    Cari Program Derived Address (PDA).
    Wrapper untuk solders find_program_address.
    """
    try:
        from solders.pubkey import Pubkey
        program_id = Pubkey.from_string(program_id_str)
        pda, bump = Pubkey.find_program_address(seeds, program_id)
        return str(pda), bump
    except Exception as e:
        logger.error(f"PDA derivation error: {e}")
        raise


def get_associated_token_address(owner: str, mint: str, token_program: str = None) -> str:
    """Hitung associated token address"""
    from solders.pubkey import Pubkey
    ASSOC_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe8bv")
    TOKEN_PROG    = Pubkey.from_string(token_program or "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    owner_pk  = Pubkey.from_string(owner)
    mint_pk   = Pubkey.from_string(mint)
    pda, _ = Pubkey.find_program_address(
        [bytes(owner_pk), bytes(TOKEN_PROG), bytes(mint_pk)],
        ASSOC_PROGRAM
    )
    return str(pda)


def derive_position_pda(lb_pair: str, owner: str, lower_bin: int, upper_bin: int,
                         program_id: str) -> Tuple[str, int]:
    """Derive PDA untuk posisi LP"""
    from solders.pubkey import Pubkey
    lb_pair_pk = Pubkey.from_string(lb_pair)
    owner_pk   = Pubkey.from_string(owner)
    lower_bytes = struct.pack("<i", lower_bin)
    upper_bytes = struct.pack("<i", upper_bin)
    seeds = [b"position", bytes(lb_pair_pk), bytes(owner_pk), lower_bytes, upper_bytes]
    return find_pda(seeds, program_id)


# ============================================================
# TRANSACTION BUILDER
# ============================================================

class SolanaTransactionBuilder:
    """
    Bangun transaksi Solana untuk interaksi dengan Meteora DLMM.
    Menggunakan solders untuk serialisasi.
    """

    def __init__(self, rpc_url: str, program_id: str):
        self.rpc_url = rpc_url
        self.program_id = program_id

    def _make_account_meta(self, pubkey_str: str, is_signer: bool, is_writable: bool):
        from solders.instruction import AccountMeta
        from solders.pubkey import Pubkey
        return AccountMeta(
            pubkey=Pubkey.from_string(pubkey_str),
            is_signer=is_signer,
            is_writable=is_writable,
        )

    async def build_initialize_position_ix(
        self,
        lb_pair: str,
        position_pda: str,
        owner: str,
        lower_bin_id: int,
        upper_bin_id: int,
    ):
        """Buat instruksi initialize_position"""
        from solders.instruction import Instruction, AccountMeta
        from solders.pubkey import Pubkey

        program = Pubkey.from_string(self.program_id)
        AM = self._make_account_meta

        accounts = [
            AM(lb_pair,      False, True),   # lb_pair
            AM(position_pda, False, True),   # position
            AM(owner,        True,  True),   # owner / payer
            AM("11111111111111111111111111111111", False, False),  # system_program
            AM("SysvarRent111111111111111111111111111111111", False, False),  # rent
        ]

        # Encode instruction data: discriminator + lower_bin_id (i32) + width (i32)
        width = upper_bin_id - lower_bin_id + 1
        data = DISC_INITIALIZE_POSITION + struct.pack("<ii", lower_bin_id, width)

        return Instruction(program_id=program, accounts=accounts, data=data)

    async def build_add_liquidity_ix(
        self,
        lb_pair: str,
        position_pda: str,
        owner: str,
        user_token_x: str,
        user_token_y: str,
        reserve_x: str,
        reserve_y: str,
        token_x_mint: str,
        token_y_mint: str,
        amount_x: int,
        amount_y: int,
        lower_bin_id: int,
        upper_bin_id: int,
        token_program_x: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        token_program_y: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    ):
        """Buat instruksi add_liquidity_by_strategy (Spot strategy)"""
        from solders.instruction import Instruction
        from solders.pubkey import Pubkey

        program = Pubkey.from_string(self.program_id)
        AM = self._make_account_meta

        event_authority, _ = find_pda([b"__event_authority"], self.program_id)

        accounts = [
            AM(lb_pair,        False, True),
            AM(position_pda,   False, True),
            AM(user_token_x,   False, True),
            AM(user_token_y,   False, True),
            AM(reserve_x,      False, True),
            AM(reserve_y,      False, True),
            AM(token_x_mint,   False, False),
            AM(token_y_mint,   False, False),
            AM(owner,          True,  True),
            AM(token_program_x, False, False),
            AM(token_program_y, False, False),
            AM(event_authority, False, False),
            AM(self.program_id, False, False),
        ]

        # LiquidityParameterByStrategy:
        # amount_x: u64, amount_y: u64, active_id: i32,
        # max_active_bin_slippage: i32, strategy_type: u8 (0=Spot)
        # active_id dan slippage dihitung dari bin range
        active_id = (lower_bin_id + upper_bin_id) // 2
        strategy_type = 0  # Spot

        liq_params = struct.pack(
            "<QQii",
            amount_x,
            amount_y,
            active_id,
            2,  # max_active_bin_slippage
        ) + bytes([strategy_type])

        data = DISC_ADD_LIQUIDITY_BY_STRATEGY + liq_params
        return Instruction(program_id=program, accounts=accounts, data=data)

    async def build_remove_liquidity_ix(
        self,
        lb_pair: str,
        position_pda: str,
        owner: str,
        user_token_x: str,
        user_token_y: str,
        reserve_x: str,
        reserve_y: str,
        token_x_mint: str,
        token_y_mint: str,
        bin_liquidity_removal: List[Tuple[int, int]],  # [(bin_id, bps_to_remove)]
        token_program_x: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        token_program_y: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    ):
        """Buat instruksi remove_liquidity (hapus semua likuiditas)"""
        from solders.instruction import Instruction
        from solders.pubkey import Pubkey

        program = Pubkey.from_string(self.program_id)
        AM = self._make_account_meta

        event_authority, _ = find_pda([b"__event_authority"], self.program_id)

        accounts = [
            AM(lb_pair,         False, True),
            AM(position_pda,    False, True),
            AM(user_token_x,    False, True),
            AM(user_token_y,    False, True),
            AM(reserve_x,       False, True),
            AM(reserve_y,       False, True),
            AM(token_x_mint,    False, False),
            AM(token_y_mint,    False, False),
            AM(owner,           True,  True),
            AM(token_program_x, False, False),
            AM(token_program_y, False, False),
            AM(event_authority, False, False),
            AM(self.program_id, False, False),
        ]

        # BinLiquidityReduction: Vec<{bin_id: i32, bps_to_remove: u16}>
        # Encode vector: [len as u32] + [bin_id i32, bps u16] * n
        n = len(bin_liquidity_removal)
        removal_data = struct.pack("<I", n)
        for bin_id, bps in bin_liquidity_removal:
            removal_data += struct.pack("<iH", bin_id, bps)

        data = DISC_REMOVE_LIQUIDITY + removal_data
        return Instruction(program_id=program, accounts=accounts, data=data)

    async def build_claim_fee_ix(
        self,
        lb_pair: str,
        position_pda: str,
        owner: str,
        user_token_x: str,
        user_token_y: str,
        reserve_x: str,
        reserve_y: str,
        token_x_mint: str,
        token_y_mint: str,
        token_program_x: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        token_program_y: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    ):
        """Buat instruksi claim_fee"""
        from solders.instruction import Instruction
        from solders.pubkey import Pubkey

        program = Pubkey.from_string(self.program_id)
        AM = self._make_account_meta
        event_authority, _ = find_pda([b"__event_authority"], self.program_id)

        accounts = [
            AM(lb_pair,         False, True),
            AM(position_pda,    False, True),
            AM(user_token_x,    False, True),
            AM(user_token_y,    False, True),
            AM(reserve_x,       False, True),
            AM(reserve_y,       False, True),
            AM(token_x_mint,    False, False),
            AM(token_y_mint,    False, False),
            AM(owner,           True,  False),
            AM(token_program_x, False, False),
            AM(token_program_y, False, False),
            AM(event_authority, False, False),
            AM(self.program_id, False, False),
        ]

        data = DISC_CLAIM_FEE
        return Instruction(program_id=program, accounts=accounts, data=data)

    async def build_close_position_ix(
        self,
        position_pda: str,
        lb_pair: str,
        owner: str,
        rent_receiver: str,
    ):
        """Buat instruksi close_position (reclaim rent)"""
        from solders.instruction import Instruction
        from solders.pubkey import Pubkey

        program = Pubkey.from_string(self.program_id)
        AM = self._make_account_meta
        event_authority, _ = find_pda([b"__event_authority"], self.program_id)

        accounts = [
            AM(position_pda,   False, True),
            AM(lb_pair,        False, True),
            AM(rent_receiver,  False, True),
            AM(owner,          True,  False),
            AM(event_authority, False, False),
            AM(self.program_id, False, False),
        ]
        return Instruction(program_id=program, accounts=accounts, data=DISC_CLOSE_POSITION)

    async def build_create_ata_ix(self, owner: str, mint: str, payer: str,
                                    token_program: str = None):
        """Buat instruksi create associated token account"""
        from solders.instruction import Instruction, AccountMeta
        from solders.pubkey import Pubkey

        tp_str = token_program or "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        ata = get_associated_token_address(owner, mint, tp_str)

        program = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJe8bv")
        AM = self._make_account_meta

        accounts = [
            AM(payer,   True,  True),
            AM(ata,     False, True),
            AM(owner,   False, False),
            AM(mint,    False, False),
            AM("11111111111111111111111111111111", False, False),
            AM(tp_str,  False, False),
        ]
        # Instruction data kosong untuk idempotent create (versi 1)
        return Instruction(program_id=program, accounts=accounts, data=bytes([1]))

    def build_and_sign_transaction(
        self,
        instructions: list,
        payer_keypair,
        blockhash: str,
        additional_signers: list = None,
    ) -> str:
        """
        Gabungkan instruksi, sign, dan encode ke base64.
        Returns base64-encoded signed transaction.
        """
        from solders.transaction import Transaction
        from solders.message import Message
        from solders.hash import Hash
        from solders.pubkey import Pubkey

        signers = [payer_keypair] + (additional_signers or [])
        recent_hash = Hash.from_string(blockhash)

        msg = Message.new_with_blockhash(
            instructions,
            Pubkey.from_string(str(payer_keypair.pubkey())),
            recent_hash,
        )
        tx = Transaction.new_unsigned(msg)
        tx.sign(signers, recent_hash)

        serialized = bytes(tx)
        return base64.b64encode(serialized).decode()
