"""
Top LPers Analyzer - Pelajari strategi LP terbaik di pool target
Terinspirasi dari Meridian's study_top_lpers tool
"""

import aiohttp
import json
import logging
from typing import List, Dict, Optional
from config import BotConfig
from lessons import LessonsManager

logger = logging.getLogger(__name__)

METEORA_API = "https://dlmm-api.meteora.ag"
LPAGENT_API = "https://api.lpagent.io"  # opsional


class TopLPersAnalyzer:
    def __init__(self, config: BotConfig, lessons_manager: LessonsManager):
        self.config = config
        self.lessons = lessons_manager

    async def get_top_lpers(self, pool_address: str, limit: int = 10) -> List[Dict]:
        """Ambil daftar top LPers dari pool"""
        async with aiohttp.ClientSession() as session:
            try:
                # Coba Meteora API
                async with session.get(
                    f"{METEORA_API}/pair/{pool_address}/top_lpers",
                    params={"limit": limit},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception:
                pass

            # Fallback: ambil posisi aktif terbesar
            try:
                async with session.get(
                    f"{METEORA_API}/position/by_pair/{pool_address}",
                    params={"limit": 20},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        positions = await resp.json()
                        # Sort by fee earned
                        if isinstance(positions, list):
                            positions.sort(
                                key=lambda p: float(p.get("total_fee_earned_usd", 0)),
                                reverse=True
                            )
                            return positions[:limit]
            except Exception as e:
                logger.warning(f"Error fetching top lpers: {e}")

        return []

    async def get_wallet_positions(self, wallet_address: str) -> List[Dict]:
        """Ambil semua posisi LP dari wallet tertentu"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{METEORA_API}/position/owner/{wallet_address}",
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception as e:
                logger.warning(f"Error fetching wallet positions: {e}")
        return []

    async def analyze_lper_behavior(self, lper_data: List[Dict]) -> Dict:
        """Analisis pola behavior dari top LPers"""
        if not lper_data:
            return {}

        total = len(lper_data)
        profitable = sum(1 for l in lper_data if float(l.get("total_fee_earned_usd", 0)) > 0)

        # Rata-rata durasi posisi (jika ada data)
        durations = [
            float(l.get("duration_hours", 0))
            for l in lper_data
            if l.get("duration_hours")
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0

        # Fee range paling sering digunakan
        fee_tiers = [l.get("fee_tier", "1%") for l in lper_data if l.get("fee_tier")]

        return {
            "total_analyzed": total,
            "profitable_count": profitable,
            "win_rate_pct": (profitable / total * 100) if total > 0 else 0,
            "avg_hold_duration_hours": round(avg_duration, 1),
            "common_fee_tier": max(set(fee_tiers), key=fee_tiers.count) if fee_tiers else "unknown",
            "top_lpers": lper_data[:3],
        }

    async def study_and_save_lessons(
        self, pool_addresses: List[str], llm_advisor
    ) -> List[str]:
        """
        Pelajari top LPers di beberapa pool dan simpan lessons.
        Menggunakan LLM untuk ekstrak insight.
        """
        all_data = {}

        for pool_addr in pool_addresses:
            logger.info(f"🔍 Studying top LPers in {pool_addr[:8]}...")
            lpers = await self.get_top_lpers(pool_addr, limit=10)
            if lpers:
                analysis = await self.analyze_lper_behavior(lpers)
                all_data[pool_addr] = analysis

        if not all_data:
            logger.warning("Tidak ada data top LPers yang berhasil diambil")
            return []

        # Minta LLM untuk ekstrak lessons
        lessons_text = await llm_advisor.extract_lper_lessons(all_data)

        if lessons_text:
            self.lessons.add_lessons(
                lessons_text,
                source_pool="multi-pool",
                applies_to="screening"
            )
            logger.info(f"💡 {len(lessons_text)} lessons disimpan dari study top LPers")
            return lessons_text

        return []
