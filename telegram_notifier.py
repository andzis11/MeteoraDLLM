"""
Telegram Notifier - Notifikasi + 2-arah chat via Telegram
Auto-register chat ID, full command support, free-form chat via bot
"""

import aiohttp
import asyncio
import logging
from typing import Optional, TYPE_CHECKING
from config import BotConfig

if TYPE_CHECKING:
    from scheduler import BotScheduler

logger = logging.getLogger(__name__)
TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self, config: BotConfig, state_manager=None):
        self.token = config.telegram_bot_token
        self.config = config
        self.state = state_manager
        self.enabled = bool(self.token)
        self._last_update_id = 0
        self._scheduler: Optional["BotScheduler"] = None

        if not self.enabled:
            logger.warning("⚠️  Telegram tidak dikonfigurasi - notifikasi dimatikan")

    def set_scheduler(self, scheduler: "BotScheduler"):
        self._scheduler = scheduler

    def _get_chat_ids(self) -> list:
        if self.state and self.state.state.telegram_chat_ids:
            return self.state.state.telegram_chat_ids
        if self.config.telegram_chat_id:
            return [self.config.telegram_chat_id]
        return []

    async def send(self, message: str, chat_id: str = None):
        if not self.enabled:
            logger.info(f"[TG] {message[:80]}")
            return
        targets = [chat_id] if chat_id else self._get_chat_ids()
        if not targets:
            return
        url = f"{TELEGRAM_API}/bot{self.token}/sendMessage"
        for cid in targets:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json={
                        "chat_id": cid, "text": message, "parse_mode": "HTML",
                    }, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            logger.error(f"TG error: {await resp.json()}")
            except Exception as e:
                logger.error(f"TG send error: {e}")

    async def start_polling(self):
        """Polling pesan masuk (2-arah chat)"""
        if not self.enabled:
            return
        logger.info("📱 Telegram polling aktif - kirim pesan ke bot untuk registrasi")
        while True:
            try:
                await self._poll_updates()
            except Exception as e:
                logger.warning(f"Poll error: {e}")
            await asyncio.sleep(3)

    async def _poll_updates(self):
        url = f"{TELEGRAM_API}/bot{self.token}/getUpdates"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={
                "offset": self._last_update_id + 1,
                "timeout": 10,
                "allowed_updates": ["message"]
            }, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    await self._handle_update(update)

    async def _handle_update(self, update: dict):
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip()
        if not chat_id or not text:
            return
        if self.state:
            self.state.register_telegram_chat(chat_id)
        await self._process_message(chat_id, text)

    async def _process_message(self, chat_id: str, text: str):
        if not self._scheduler:
            await self.send("Bot belum siap.", chat_id)
            return
        sch = self._scheduler

        if text == "/start":
            await self.send(
                "🤖 <b>Meridian LP Bot</b>\n\n"
                "/status - Status & posisi aktif\n"
                "/candidates - Pool terbaik\n"
                "/learn - Pelajari top LPers\n"
                "/thresholds - Lihat thresholds\n"
                "/evolve - Evolusi threshold (5+ posisi)\n\n"
                "Atau chat bebas, contoh:\n"
                "<i>\"Bagaimana performa bot hari ini?\"</i>\n"
                "<i>\"Analisis pool xyz...\"</i>",
                chat_id
            )
            return

        if text == "/status":
            lm = sch.lp_manager
            stats = sch.lessons.get_performance_stats()
            balance = await lm.get_sol_balance()
            msg = (f"📊 <b>Status Bot</b>\n"
                   f"Mode: {'🟡 Simulasi' if lm._simulation_mode else '🟢 Live'}\n"
                   f"Balance: <b>{balance:.3f} SOL</b>\n"
                   f"Posisi aktif: <b>{lm.active_position_count}</b>\n")
            for pos in lm.positions.values():
                icon = "✅" if pos.is_in_range else "⚠️"
                msg += f"{icon} {pos.pool_name}: {pos.fee_return_pct:.1f}%\n"
            if stats["total"] > 0:
                msg += f"\nWin rate: {stats['win_rate']:.0f}% ({stats['total']} posisi)"
            await self.send(msg, chat_id)
            return

        if text == "/candidates":
            candidates = sch.state.state.last_candidates
            if not candidates:
                await self.send("❌ Belum ada kandidat. Tunggu scan berikutnya.", chat_id)
                return
            msg = f"🔍 <b>Top Pool Candidates</b>\n"
            for i, c in enumerate(candidates[:5], 1):
                msg += f"{i}. <code>{c.get('name','?')[:18]}</code> APR:{c.get('apr',0):.0f}%\n"
            await self.send(msg, chat_id)
            return

        if text == "/thresholds":
            cfg = sch.config
            await self.send(
                f"🔧 <b>Thresholds</b>\n"
                f"Organic score min: {cfg.min_organic_score}\n"
                f"Holders min: {cfg.min_token_holders}\n"
                f"Volatility max: {cfg.max_pool_volatility}\n"
                f"Take profit: {cfg.take_profit_pct}%\n"
                f"OOR timeout: {cfg.out_of_range_minutes} mnt", chat_id
            )
            return

        if text.startswith("/learn"):
            await self.send("📚 Mempelajari top LPers...", chat_id)
            pool_addrs = [c.get("address", "") for c in sch.state.state.last_candidates[:3]]
            lessons = await sch.top_lpers.study_and_save_lessons(pool_addrs, sch.llm)
            if lessons:
                msg = f"💡 <b>{len(lessons)} Lessons Baru</b>\n"
                for i, l in enumerate(lessons[:5], 1):
                    msg += f"{i}. {l}\n"
                await self.send(msg, chat_id)
            else:
                await self.send("❌ Tidak ada lessons diekstrak.", chat_id)
            return

        if text == "/evolve":
            stats = sch.lessons.get_performance_stats()
            if stats["total"] < 5:
                await self.send(f"❌ Butuh 5+ posisi. Saat ini: {stats['total']}", chat_id)
                return
            await self.send("🧬 Evolving thresholds...", chat_id)
            import json as _json
            cfg_dict = {
                "min_organic_score": sch.config.min_organic_score,
                "min_token_holders": sch.config.min_token_holders,
                "take_profit_pct": sch.config.take_profit_pct,
            }
            result = await sch.llm.suggest_threshold_evolution(cfg_dict, stats, sch.lessons.get_threshold_suggestions())
            changes = result.get("changes", [])
            if changes:
                msg = f"✅ <b>{len(changes)} Perubahan</b>\n"
                for c in changes:
                    msg += f"• {c['field']}: {c['old']} → {c['new']}\n"
                    if hasattr(sch.config, c["field"]):
                        setattr(sch.config, c["field"], c["new"])
                await self.send(msg, chat_id)
            else:
                await self.send("Tidak ada perubahan diperlukan.", chat_id)
            return

        # Free-form chat
        import json as _json
        extra = ""
        if sch.lp_manager.positions:
            extra = f"\nPosisi aktif: {_json.dumps([p.to_dict() for p in sch.lp_manager.positions.values()])}"
        response = await sch.llm.chat(text, extra_context=extra)
        await self.send(f"🤖 {response}", chat_id)

    # === NOTIFIKASI ===
    async def notify_position_opened(self, pool_name: str, sol: float, addr: str):
        await self.send(f"🟢 <b>Posisi Dibuka</b>\n<code>{pool_name}</code>\n<b>{sol:.3f} SOL</b>\n{addr[:16]}...")

    async def notify_position_closed(self, pool_name: str, sol: float, fees: float, reason: str):
        pct = (fees / sol * 100) if sol > 0 else 0
        emoji = "💰" if fees > 0 else "🔴"
        await self.send(f"{emoji} <b>Posisi Ditutup</b>\n<code>{pool_name}</code>\nReturn: <b>{fees:.4f} SOL ({pct:.1f}%)</b>\n{reason}")

    async def notify_out_of_range(self, pool_name: str, minutes: float):
        await self.send(f"⚠️ <b>Out of Range!</b>\n{pool_name} sudah {minutes:.0f} menit OOR")

    async def notify_cycle_report(self, report: str, cycle_type: str):
        await self.send(f"📋 <b>{cycle_type} Report</b>\n{report}")

    async def notify_status(self, active: int, sol: float, fees: float, balance: float):
        await self.send(f"📊 Posisi: <b>{active}</b> | Deployed: <b>{sol:.3f}</b> | Fee: <b>{fees:.4f}</b> | Balance: <b>{balance:.3f}</b> SOL")

    async def notify_error(self, error: str):
        await self.send(f"⚠️ <b>Error</b>\n<code>{error[:200]}</code>")
