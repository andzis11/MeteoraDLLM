"""
Lessons System - Bot belajar dari performa posisi dan top LPers
Terinspirasi dari Meridian's learning system
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

LESSONS_FILE = "lessons.json"
HISTORY_FILE = "position_history.json"


@dataclass
class Lesson:
    content: str
    source_pool: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    applies_to: str = "general"  # "screening" | "management" | "general"
    confidence: float = 0.8


@dataclass
class ClosedPosition:
    pool_address: str
    pool_name: str
    sol_deployed: float
    fees_earned_sol: float
    duration_minutes: float
    close_reason: str
    closed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    pnl_sol: float = 0.0

    @property
    def fee_return_pct(self) -> float:
        if self.sol_deployed == 0:
            return 0
        return (self.fees_earned_sol / self.sol_deployed) * 100

    @property
    def was_profitable(self) -> bool:
        return self.fees_earned_sol > 0


class LessonsManager:
    def __init__(self):
        self.lessons: List[Lesson] = []
        self.closed_positions: List[ClosedPosition] = []
        self._load()

    def _load(self):
        """Load lessons dan history dari file"""
        if os.path.exists(LESSONS_FILE):
            try:
                with open(LESSONS_FILE, "r") as f:
                    data = json.load(f)
                    self.lessons = [Lesson(**l) for l in data]
                logger.info(f"📚 Loaded {len(self.lessons)} lessons")
            except Exception as e:
                logger.warning(f"Error loading lessons: {e}")

        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    data = json.load(f)
                    self.closed_positions = [ClosedPosition(**p) for p in data]
                logger.info(f"📊 Loaded {len(self.closed_positions)} position history")
            except Exception as e:
                logger.warning(f"Error loading history: {e}")

    def _save_lessons(self):
        with open(LESSONS_FILE, "w") as f:
            json.dump([asdict(l) for l in self.lessons], f, indent=2)

    def _save_history(self):
        with open(HISTORY_FILE, "w") as f:
            json.dump([asdict(p) for p in self.closed_positions], f, indent=2)

    def add_closed_position(self, pool_address: str, pool_name: str,
                             sol_deployed: float, fees_earned: float,
                             duration_minutes: float, close_reason: str):
        """Simpan posisi yang sudah ditutup ke history"""
        cp = ClosedPosition(
            pool_address=pool_address,
            pool_name=pool_name,
            sol_deployed=sol_deployed,
            fees_earned_sol=fees_earned,
            duration_minutes=duration_minutes,
            close_reason=close_reason,
            pnl_sol=fees_earned,
        )
        self.closed_positions.append(cp)
        self._save_history()
        logger.info(f"📊 History saved: {pool_name} | {cp.fee_return_pct:.1f}% return")

    def add_lessons(self, new_lessons: List[str], source_pool: str, applies_to: str = "general"):
        """Tambah lessons baru"""
        for content in new_lessons:
            lesson = Lesson(content=content, source_pool=source_pool, applies_to=applies_to)
            self.lessons.append(lesson)
        self._save_lessons()
        logger.info(f"💡 Saved {len(new_lessons)} new lessons from {source_pool}")

    def get_lessons_context(self, max_lessons: int = 8) -> str:
        """Ambil lessons terbaru untuk diinjeksi ke LLM context"""
        if not self.lessons:
            return ""
        recent = self.lessons[-max_lessons:]
        lines = ["=== LESSONS FROM PAST EXPERIENCE ==="]
        for i, l in enumerate(recent, 1):
            lines.append(f"{i}. [{l.applies_to.upper()}] {l.content}")
        return "\n".join(lines)

    def get_performance_stats(self) -> Dict:
        """Hitung statistik performa dari closed positions"""
        if not self.closed_positions:
            return {"total": 0, "win_rate": 0, "avg_return_pct": 0, "avg_duration_min": 0}

        wins = [p for p in self.closed_positions if p.was_profitable]
        returns = [p.fee_return_pct for p in self.closed_positions]
        durations = [p.duration_minutes for p in self.closed_positions]

        return {
            "total": len(self.closed_positions),
            "wins": len(wins),
            "losses": len(self.closed_positions) - len(wins),
            "win_rate": len(wins) / len(self.closed_positions) * 100,
            "avg_return_pct": sum(returns) / len(returns),
            "max_return_pct": max(returns),
            "avg_duration_min": sum(durations) / len(durations),
            "total_fees_sol": sum(p.fees_earned_sol for p in self.closed_positions),
        }

    def get_threshold_suggestions(self) -> Optional[Dict]:
        """Saran perubahan threshold berdasarkan performance (min 5 posisi)"""
        if len(self.closed_positions) < 5:
            return None

        stats = self.get_performance_stats()
        suggestions = {}

        # Jika win rate rendah, perketat filter
        if stats["win_rate"] < 50:
            suggestions["min_organic_score"] = "+5 (win rate rendah)"
            suggestions["min_token_holders"] = "+100 (butuh kualitas lebih tinggi)"

        # Jika return rata-rata bagus, bisa turunkan take profit target
        if stats["avg_return_pct"] > 20:
            suggestions["take_profit_pct"] = "-2% (return tinggi, ambil lebih cepat)"

        # Jika durasi lama dan return kecil, perketat OOR timeout
        if stats["avg_duration_min"] > 120 and stats["avg_return_pct"] < 5:
            suggestions["out_of_range_minutes"] = "-5 (exit lebih cepat)"

        return suggestions if suggestions else None
