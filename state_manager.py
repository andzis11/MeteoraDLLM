"""
State Manager - Simpan dan load state bot secara persisten
Terinspirasi dari Meridian's state.js
"""

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

STATE_FILE = "bot_state.json"


@dataclass
class BotState:
    """State persisten bot"""
    # Candidates pool terakhir
    last_candidates: List[Dict] = field(default_factory=list)
    last_scan_time: str = ""

    # Config thresholds (bisa di-evolve)
    current_thresholds: Dict = field(default_factory=dict)

    # Telegram
    telegram_chat_ids: List[str] = field(default_factory=list)

    # Session history untuk LLM chat
    chat_history: List[Dict] = field(default_factory=list)

    # Stats
    total_cycles_run: int = 0
    bot_started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_chat(self, role: str, content: str, max_history: int = 10):
        """Tambah pesan ke chat history (rolling window)"""
        self.chat_history.append({"role": role, "content": content})
        if len(self.chat_history) > max_history * 2:
            self.chat_history = self.chat_history[-max_history * 2:]

    def clear_chat(self):
        self.chat_history = []


class StateManager:
    def __init__(self):
        self.state = BotState()
        self._load()

    def _load(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                # Update state dengan data yang ada
                for key, val in data.items():
                    if hasattr(self.state, key):
                        setattr(self.state, key, val)
                logger.info("✅ State loaded dari file")
            except Exception as e:
                logger.warning(f"Error loading state: {e}")

    def save(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(asdict(self.state), f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def update_candidates(self, candidates: List[Dict]):
        self.state.last_candidates = candidates
        self.state.last_scan_time = datetime.now().isoformat()
        self.save()

    def update_threshold(self, key: str, value: Any, reason: str = ""):
        self.state.current_thresholds[key] = {"value": value, "reason": reason}
        self.save()
        logger.info(f"🔧 Threshold updated: {key} = {value} ({reason})")

    def register_telegram_chat(self, chat_id: str):
        if chat_id not in self.state.telegram_chat_ids:
            self.state.telegram_chat_ids.append(chat_id)
            self.save()
            logger.info(f"✅ Telegram chat registered: {chat_id}")

    def increment_cycle(self):
        self.state.total_cycles_run += 1
        self.save()

    def add_chat_message(self, role: str, content: str):
        self.state.add_chat(role, content)
        self.save()

    def get_chat_history(self) -> List[Dict]:
        return self.state.chat_history

    def clear_chat_history(self):
        self.state.clear_chat()
        self.save()
