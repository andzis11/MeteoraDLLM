"""
Konfigurasi Bot - Edit file ini sesuai kebutuhan kamu
"""

import os
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class BotConfig:
    # === WALLET & RPC ===
    wallet_private_key: str = ""           # Private key Solana (base58)
    rpc_url: str = "https://pump.helius-rpc.com"

    # === DEPLOYMENT ===
    sol_per_position: float = 0.3          # SOL per posisi LP
    max_concurrent_positions: int = 2      # Maks posisi aktif bersamaan
    min_sol_balance: float = 0.3           # Min SOL sebelum buka posisi baru
    max_sol_per_position: float = 1.0      # Safety cap SOL per posisi

    # === RISK & FILTERS ===
    pool_discovery_interval: int = 30      # menit (30m / 60m / 240m / 720m / 1440m)
    max_pool_volatility: float = 10.0      # Max volatilitas pool
    max_price_change_pct: float = 200.0    # Max perubahan harga (%)
    min_organic_score: int = 75            # Skor organik minimum (0-100)
    min_token_holders: int = 500           # Min jumlah holder token
    max_market_cap_usd: float = 3_000_000  # Max market cap USD

    # === EXIT RULES ===
    take_profit_pct: float = 15.0          # Ambil profit saat fee >= X% modal
    out_of_range_minutes: int = 10         # Tutup posisi jika OOR lebih dari X menit

    # === SCHEDULING ===
    management_cycle_minutes: int = 5      # Interval cek posisi aktif
    screening_cycle_minutes: int = 15      # Interval scan pool baru

    # === MINIMAX LLM ===
    minimax_api_key: str = ""              # API key MiniMax kamu
    minimax_api_url: str = "https://api.minimax.io/v1/text/chatcompletion_v2"
    minimax_model: str = "MiniMax-Text-01"

    # === TELEGRAM ===
    telegram_bot_token: str = ""           # Token bot Telegram kamu
    telegram_chat_id: str = ""             # Chat ID / Group ID kamu

    @classmethod
    def load(cls) -> "BotConfig":
        """Load config dari environment variables atau gunakan default"""
        return cls(
            wallet_private_key=os.getenv("WALLET_PRIVATE_KEY", ""),
            rpc_url=os.getenv("RPC_URL", "https://pump.helius-rpc.com"),
            minimax_api_key=os.getenv("MINIMAX_API_KEY", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        )
