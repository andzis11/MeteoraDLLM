"""
LLM Advisor - ReAct agent loop dengan MiniMax
Hunter Alpha (screening) + Healer Alpha (management)
Dengan lessons injection, persistent chat history, dan cycle reports
"""

import aiohttp
import json
import logging
from typing import List, Optional, Dict
from pool_scanner import PoolInfo
from config import BotConfig

logger = logging.getLogger(__name__)


class MiniMaxLLM:
    def __init__(self, config: BotConfig, lessons_manager=None, state_manager=None):
        self.config = config
        self.api_url = config.minimax_api_url
        self.api_key = config.minimax_api_key
        self.model = config.minimax_model
        self.lessons = lessons_manager
        self.state = state_manager

    async def _call(self, system: str, messages: List[Dict], max_tokens: int = 800) -> Optional[str]:
        if not self.api_key:
            logger.warning("MiniMax API key tidak diset")
            return None
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=45)
                ) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        return data["choices"][0]["message"]["content"]
                    logger.error(f"MiniMax {resp.status}: {data}")
                    return None
        except Exception as e:
            logger.error(f"LLM call error: {e}")
            return None

    def _lessons_ctx(self) -> str:
        return self.lessons.get_lessons_context() if self.lessons else ""

    def _perf_ctx(self) -> str:
        if not self.lessons:
            return ""
        s = self.lessons.get_performance_stats()
        if s["total"] == 0:
            return ""
        return (f"\n=== PERFORMANCE ===\nTotal: {s['total']} | Win: {s['win_rate']:.0f}%"
                f" | Avg return: {s['avg_return_pct']:.1f}% | Fees: {s['total_fees_sol']:.4f} SOL")

    # === HUNTER ALPHA ===
    async def rank_pools(self, pools: List[PoolInfo]) -> List[PoolInfo]:
        if not pools:
            return []
        pool_data = json.dumps([p.to_dict() for p in pools[:5]], indent=2)
        system = f"""Kamu adalah Hunter Alpha — agen screening pool Meteora DLMM.
Gunakan ReAct: THINK → ANALYZE → DECIDE.
{self._lessons_ctx()}{self._perf_ctx()}
Jawab HANYA JSON valid setelah DECIDE:"""

        user = f"""Pools:\n{pool_data}\n\nFormat:\nTHINK: ...\nANALYZE: ...\nDECIDE: {{"ranking":["addr1"],"best_pool":"addr1","reasoning":"...","risk_level":"LOW/MEDIUM/HIGH","confidence":0.8}}"""

        response = await self._call(system, [{"role": "user", "content": user}])
        if not response:
            return pools
        try:
            json_part = response.split("DECIDE:")[-1].strip() if "DECIDE:" in response else response
            if "```" in json_part:
                json_part = json_part.split("```")[1].replace("json", "").strip()
            result = json.loads(json_part)
            ranking = result.get("ranking", [])
            logger.info(f"🎯 Hunter [{result.get('risk_level','?')}] {result.get('confidence',0):.0%}: {result.get('reasoning','')}")
            pool_map = {p.address: p for p in pools}
            ranked = [pool_map[a] for a in ranking if a in pool_map]
            ranked += [p for p in pools if p.address not in ranking]
            return ranked
        except Exception as e:
            logger.warning(f"Hunter parse error: {e}")
            return pools

    # === HEALER ALPHA ===
    async def should_close_position(self, position: dict) -> bool:
        system = f"""Kamu adalah Healer Alpha — agen manajemen posisi LP.
Putuskan: STAY, CLOSE, atau REDEPLOY.
{self._lessons_ctx()}
Jawab JSON: {{"action":"STAY|CLOSE|REDEPLOY","reason":"..."}}"""
        response = await self._call(system, [{"role": "user", "content": json.dumps(position, indent=2)}])
        if not response:
            return False
        try:
            clean = response.strip()
            if "```" in clean:
                clean = clean.split("```")[1].replace("json", "").strip()
            result = json.loads(clean)
            action = result.get("action", "STAY")
            if action != "STAY":
                logger.info(f"🩺 Healer [{action}]: {result.get('reason','')}")
            return action in ("CLOSE", "REDEPLOY")
        except Exception:
            return False

    # === FREE-FORM CHAT ===
    async def chat(self, user_message: str, extra_context: str = "") -> str:
        system = f"""Kamu adalah asisten bot LP Meteora DLMM yang cerdas.
Jawab dalam Bahasa Indonesia yang natural dan informatif.
{self._lessons_ctx()}{self._perf_ctx()}
{extra_context}"""
        history = self.state.get_chat_history()[-10:] if self.state else []
        messages = history + [{"role": "user", "content": user_message}]
        response = await self._call(system, messages, max_tokens=600)
        if self.state and response:
            self.state.add_chat_message("user", user_message)
            self.state.add_chat_message("assistant", response)
        return response or "Maaf, tidak bisa memproses permintaan."

    # === LESSONS EXTRACTION ===
    async def extract_lper_lessons(self, lper_data: Dict) -> List[str]:
        system = """Analis DeFi expert. Ekstrak 4-8 lessons konkret dari data top LPers.
Prioritaskan pola yang muncul di banyak pool.
Jawab HANYA JSON array of strings."""
        user = f"Data:\n{json.dumps(lper_data, indent=2)}\n\nFormat: [\"lesson1\", \"lesson2\"]"
        response = await self._call(system, [{"role": "user", "content": user}])
        if not response:
            return []
        try:
            clean = response.strip()
            if "```" in clean:
                clean = clean.split("```")[1].replace("json", "").strip()
            return [l for l in json.loads(clean) if isinstance(l, str)]
        except Exception:
            return []

    # === THRESHOLD EVOLUTION ===
    async def suggest_threshold_evolution(self, current_config: dict,
                                           performance_stats: dict,
                                           manual_suggestions: Optional[dict] = None) -> dict:
        system = """Optimizer strategi DeFi. Analisis performa dan sarankan perubahan threshold.
Jawab HANYA JSON: {"changes":[{"field":"...","old":...,"new":...,"reason":"..."}]}"""
        user = f"""Config: {json.dumps(current_config, indent=2)}
Stats: {json.dumps(performance_stats, indent=2)}
{"Saran manual: " + json.dumps(manual_suggestions) if manual_suggestions else ""}"""
        response = await self._call(system, [{"role": "user", "content": user}], max_tokens=500)
        if not response:
            return {"changes": []}
        try:
            clean = response.strip()
            if "```" in clean:
                clean = clean.split("```")[1].replace("json", "").strip()
            return json.loads(clean)
        except Exception:
            return {"changes": []}

    # === CYCLE REPORT ===
    async def generate_cycle_report(self, cycle_type: str, actions_taken: List[str],
                                     positions_summary: List[dict]) -> str:
        system = "Reporter bot LP. Buat ringkasan cycle yang informatif dalam Bahasa Indonesia."
        user = f"Cycle: {cycle_type}\nAksi: {json.dumps(actions_taken)}\nPosisi: {json.dumps(positions_summary)}\n\nRingkasan 3-5 kalimat."
        response = await self._call(system, [{"role": "user", "content": user}], max_tokens=300)
        return response or f"Cycle {cycle_type} selesai."
