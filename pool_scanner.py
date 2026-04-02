"""
Pool Scanner - Scan dan filter pool terbaik di Meteora DLMM
"""

import aiohttp
import logging
from dataclasses import dataclass
from typing import List, Optional
from config import BotConfig

logger = logging.getLogger(__name__)

METEORA_API = "https://dlmm-api.meteora.ag"

@dataclass
class PoolInfo:
    address: str
    name: str
    token_x: str
    token_y: str
    fee_pct: float
    tvl_usd: float
    volume_24h: float
    apr: float
    volatility: float
    price_change_pct: float
    organic_score: int
    token_holders: int
    market_cap_usd: float

    @property
    def fee_tvl_ratio(self) -> float:
        """Rasio fee/TVL sebagai proxy profitabilitas"""
        if self.tvl_usd == 0:
            return 0
        return self.volume_24h * (self.fee_pct / 100) / self.tvl_usd

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "name": self.name,
            "fee_pct": self.fee_pct,
            "tvl_usd": self.tvl_usd,
            "volume_24h": self.volume_24h,
            "apr": self.apr,
            "volatility": self.volatility,
            "organic_score": self.organic_score,
            "token_holders": self.token_holders,
            "market_cap_usd": self.market_cap_usd,
        }


class PoolScanner:
    def __init__(self, config: BotConfig):
        self.config = config

    async def fetch_pools(self) -> List[dict]:
        """Ambil daftar pool dari Meteora API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{METEORA_API}/pair/all_with_pagination",
                    params={"page": 0, "limit": 100, "sort_key": "volume", "order_by": "desc"},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", data) if isinstance(data, dict) else data
                    else:
                        logger.error(f"Meteora API error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching pools: {e}")
            return []

    def parse_pool(self, raw: dict) -> Optional[PoolInfo]:
        """Parse raw pool data ke PoolInfo"""
        try:
            return PoolInfo(
                address=raw.get("address", ""),
                name=raw.get("name", "UNKNOWN"),
                token_x=raw.get("mint_x", ""),
                token_y=raw.get("mint_y", ""),
                fee_pct=float(raw.get("base_fee_percentage", 1.0)),
                tvl_usd=float(raw.get("liquidity", 0)),
                volume_24h=float(raw.get("trade_volume_24h", 0)),
                apr=float(raw.get("apr", 0)),
                volatility=float(raw.get("volatility", 0)),
                price_change_pct=abs(float(raw.get("price_change_24h_pct", 0))),
                organic_score=int(raw.get("organic_score", 0)),
                token_holders=int(raw.get("holder_count", 0)),
                market_cap_usd=float(raw.get("market_cap", 0)),
            )
        except Exception as e:
            logger.warning(f"Error parsing pool {raw.get('address', '')}: {e}")
            return None

    def filter_pools(self, pools: List[PoolInfo]) -> List[PoolInfo]:
        """Filter pool berdasarkan risk & filter config"""
        filtered = []
        cfg = self.config

        for pool in pools:
            # Skip SOL/USDC pairs (terlalu kompetitif)
            if pool.tvl_usd < 10_000:
                continue
            if pool.volatility > cfg.max_pool_volatility:
                continue
            if pool.price_change_pct > cfg.max_price_change_pct:
                continue
            if pool.organic_score < cfg.min_organic_score:
                continue
            if pool.token_holders < cfg.min_token_holders:
                continue
            if cfg.max_market_cap_usd > 0 and pool.market_cap_usd > cfg.max_market_cap_usd:
                continue

            filtered.append(pool)

        # Sort by APR descending
        filtered.sort(key=lambda p: p.apr, reverse=True)
        return filtered[:10]  # Top 10

    async def scan(self) -> List[PoolInfo]:
        """Scan dan filter pool terbaik"""
        logger.info("🔍 Scanning Meteora pools...")
        raw_pools = await self.fetch_pools()

        if not raw_pools:
            logger.warning("No pools fetched from Meteora API")
            return []

        parsed = [p for raw in raw_pools if (p := self.parse_pool(raw)) is not None]
        filtered = self.filter_pools(parsed)

        logger.info(f"✅ Found {len(filtered)} qualifying pools from {len(parsed)} total")
        return filtered
