"""
Bot Scheduler - Orchestrator utama dengan dual agent loop
Hunter Alpha (screening) + Healer Alpha (management) + REPL + Telegram polling
Terinspirasi dari Meridian's agent architecture
"""

import asyncio
import logging
import time
from config import BotConfig
from pool_scanner import PoolScanner
from lp_manager import LPManager
from llm_advisor import MiniMaxLLM
from telegram_notifier import TelegramNotifier
from lessons import LessonsManager
from state_manager import StateManager
from top_lpers import TopLPersAnalyzer

logger = logging.getLogger(__name__)


class BotScheduler:
    def __init__(self, config: BotConfig):
        self.config = config
        self._running = True

        # Core components
        self.lessons = LessonsManager()
        self.state = StateManager()
        self.scanner = PoolScanner(config)
        self.lp_manager = LPManager(config)
        self.llm = MiniMaxLLM(config, lessons_manager=self.lessons, state_manager=self.state)
        self.telegram = TelegramNotifier(config, state_manager=self.state)
        self.top_lpers = TopLPersAnalyzer(config, self.lessons)

        # Inject scheduler ke telegram untuk 2-arah chat
        self.telegram.set_scheduler(self)

        # Timers
        self._last_scan = 0.0
        self._last_manage = 0.0
        self._last_health = 0.0
        self._start_time = time.time()

    async def run(self):
        """Jalankan semua komponen secara bersamaan"""
        await self.telegram.send(
            "🚀 <b>Meridian LP Bot Started!</b>\n"
            "Hunter Alpha & Healer Alpha siap.\n"
            "Kirim /start untuk melihat commands."
        )
        logger.info("✅ Bot scheduler running. Ctrl+C untuk berhenti.")

        try:
            # Jalankan semua task secara parallel
            await asyncio.gather(
                self._agent_loop(),
                self._repl_loop(),
                self.telegram.start_polling(),
                return_exceptions=True
            )
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            await self.telegram.notify_error(str(e))
        finally:
            await self._shutdown()

    async def _agent_loop(self):
        """Loop utama agent (Hunter + Healer + Health check)"""
        while self._running:
            now = time.time()

            # === HUNTER ALPHA - Pool Screening ===
            scan_interval = self.config.screening_cycle_minutes * 60
            if now - self._last_scan >= scan_interval:
                await self._hunter_cycle()
                self._last_scan = time.time()

            # === HEALER ALPHA - Position Management ===
            manage_interval = self.config.management_cycle_minutes * 60
            if now - self._last_manage >= manage_interval:
                await self._healer_cycle()
                self._last_manage = time.time()

            # === HEALTH CHECK - Setiap 60 menit ===
            if now - self._last_health >= 3600:
                await self._health_check()
                self._last_health = time.time()

            self.state.increment_cycle()
            await asyncio.sleep(30)

    async def _hunter_cycle(self):
        """Hunter Alpha: scan pool dan deploy posisi baru"""
        logger.info("=" * 55)
        logger.info("🎯 Hunter Alpha: scanning pools...")
        actions = []

        try:
            pools = await self.scanner.scan()
            if not pools:
                logger.info("Hunter: tidak ada pool yang memenuhi kriteria")
                return

            # Simpan candidates ke state
            self.state.update_candidates([p.to_dict() for p in pools])

            # LLM rank pools
            ranked = await self.llm.rank_pools(pools)
            top = ranked[0] if ranked else None

            if top:
                await self.telegram.send(
                    f"🎯 <b>Hunter Alpha Report</b>\n"
                    f"Pool ditemukan: {len(pools)}\n"
                    f"Top pick: <code>{top.name}</code>"
                )

            # Deploy jika bisa
            cfg = self.config
            if self.lp_manager.active_position_count < cfg.max_concurrent_positions:
                balance = await self.lp_manager.get_sol_balance()
                if balance >= cfg.min_sol_balance + cfg.sol_per_position:
                    for pool in ranked:
                        if pool.address not in self.lp_manager.positions:
                            position = await self.lp_manager.open_position(pool)
                            if position:
                                actions.append(f"Deployed ke {pool.name}")
                                await self.telegram.notify_position_opened(
                                    pool.name, position.sol_deployed, pool.address
                                )
                            break
                else:
                    logger.warning(f"Hunter: balance kurang ({balance:.3f} SOL)")

            # Generate cycle report
            pos_summary = [p.to_dict() for p in self.lp_manager.positions.values()]
            report = await self.llm.generate_cycle_report("HUNTER", actions, pos_summary)
            await self.telegram.notify_cycle_report(report, "Hunter Alpha")

        except Exception as e:
            logger.error(f"Hunter error: {e}", exc_info=True)
            await self.telegram.notify_error(f"Hunter error: {e}")

    async def _healer_cycle(self):
        """Healer Alpha: evaluasi dan kelola posisi aktif"""
        if not self.lp_manager.positions:
            logger.info("🩺 Healer Alpha: tidak ada posisi aktif")
            return

        logger.info(f"🩺 Healer Alpha: mengelola {self.lp_manager.active_position_count} posisi...")
        actions = []

        for addr in list(self.lp_manager.positions.keys()):
            position = self.lp_manager.positions.get(addr)
            if not position:
                continue

            # Update data terbaru dari on-chain
            await self.lp_manager.update_fees_and_range(addr)

            # Notifikasi OOR
            if not position.is_in_range and position.out_of_range_minutes >= self.config.out_of_range_minutes:
                await self.telegram.notify_out_of_range(position.pool_name, position.out_of_range_minutes)

            # Cek exit conditions rule-based
            exit_reason = self.lp_manager.check_exit_conditions(position)

            # Jika tidak ada rule trigger, tanya Healer Alpha
            if not exit_reason:
                should_close = await self.llm.should_close_position(position.to_dict())
                if should_close:
                    exit_reason = "Healer Alpha merekomendasikan penutupan"

            if exit_reason:
                # Simpan ke history sebelum tutup
                self.lessons.add_closed_position(
                    pool_address=position.pool_address,
                    pool_name=position.pool_name,
                    sol_deployed=position.sol_deployed,
                    fees_earned=position.fees_earned_sol,
                    duration_minutes=position.age_minutes,
                    close_reason=exit_reason,
                )
                await self.lp_manager.close_position(addr, exit_reason)
                actions.append(f"Tutup {position.pool_name}: {exit_reason}")
                await self.telegram.notify_position_closed(
                    position.pool_name, position.sol_deployed,
                    position.fees_earned_sol, exit_reason
                )
            else:
                logger.info(
                    f"✅ {position.pool_name}: {position.age_minutes:.0f}m | "
                    f"Fee: {position.fee_return_pct:.1f}% | "
                    f"{'IN' if position.is_in_range else 'OUT'} RANGE"
                )

        # Cycle report
        pos_summary = [p.to_dict() for p in self.lp_manager.positions.values()]
        report = await self.llm.generate_cycle_report("HEALER", actions, pos_summary)
        await self.telegram.notify_cycle_report(report, "Healer Alpha")

    async def _health_check(self):
        """Health check setiap jam - ringkasan portfolio"""
        balance = await self.lp_manager.get_sol_balance()
        total_fees = sum(p.fees_earned_sol for p in self.lp_manager.positions.values())
        stats = self.lessons.get_performance_stats()

        logger.info(
            f"💚 Health Check | Balance: {balance:.3f} SOL | "
            f"Posisi: {self.lp_manager.active_position_count} | "
            f"History win rate: {stats.get('win_rate', 0):.0f}%"
        )
        await self.telegram.notify_status(
            self.lp_manager.active_position_count,
            self.lp_manager.total_sol_deployed,
            total_fees, balance
        )

    async def _repl_loop(self):
        """REPL interactive CLI"""
        from repl import REPL
        repl = REPL(self)
        await repl.run()

    async def _shutdown(self):
        """Graceful shutdown - tutup semua posisi"""
        logger.info("🛑 Shutdown: menutup semua posisi...")
        for addr in list(self.lp_manager.positions.keys()):
            position = self.lp_manager.positions.get(addr)
            if position:
                self.lessons.add_closed_position(
                    pool_address=position.pool_address,
                    pool_name=position.pool_name,
                    sol_deployed=position.sol_deployed,
                    fees_earned=position.fees_earned_sol,
                    duration_minutes=position.age_minutes,
                    close_reason="Bot shutdown",
                )
            await self.lp_manager.close_position(addr, "Bot shutdown")
        self.state.save()
        await self.telegram.send("🛑 <b>Bot dihentikan</b>. Semua posisi ditutup & state disimpan.")
