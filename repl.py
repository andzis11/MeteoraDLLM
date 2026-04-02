"""
REPL Interface - Interactive CLI dengan countdown timer
Terinspirasi dari Meridian's interactive prompt
Fitur: deploy manual, chat bebas, /status, /candidates, /learn, /evolve, /thresholds
"""

import asyncio
import logging
import sys
import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from scheduler import BotScheduler

logger = logging.getLogger(__name__)


def format_countdown(seconds: float) -> str:
    """Format detik ke MM:SS"""
    if seconds <= 0:
        return "00:00"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}m {s:02d}s"


class REPL:
    def __init__(self, scheduler: "BotScheduler"):
        self.scheduler = scheduler
        self.running = True

    def _get_prompt(self) -> str:
        """Generate prompt dengan countdown"""
        now = time.time()
        cfg = self.scheduler.config

        manage_next = (self.scheduler._last_manage + cfg.management_cycle_minutes * 60) - now
        screen_next = (self.scheduler._last_scan + cfg.screening_cycle_minutes * 60) - now

        manage_str = format_countdown(manage_next)
        screen_str = format_countdown(screen_next)

        return f"\n[manage: {manage_str} | screen: {screen_str}]\n> "

    def _print_candidates(self):
        """Tampilkan pool candidates terakhir"""
        candidates = self.scheduler.state.state.last_candidates
        if not candidates:
            print("❌ Belum ada candidates. Jalankan /candidates untuk scan.")
            return

        print(f"\n📋 Pool Candidates ({len(candidates)} pool):")
        for i, pool in enumerate(candidates[:5], 1):
            print(f"  {i}. {pool.get('name', 'UNKNOWN')[:20]:<20} "
                  f"APR: {pool.get('apr', 0):.0f}% | "
                  f"TVL: ${pool.get('tvl_usd', 0):,.0f} | "
                  f"Score: {pool.get('organic_score', 0)}")

    def _print_status(self):
        """Tampilkan status bot"""
        lm = self.scheduler.lp_manager
        lessons = self.scheduler.lessons
        stats = lessons.get_performance_stats()

        print("\n" + "="*50)
        print(f"📊 BOT STATUS - {datetime.now().strftime('%H:%M:%S')}")
        print("="*50)
        print(f"Mode: {'🟡 SIMULASI' if lm._simulation_mode else '🟢 LIVE'}")
        print(f"Posisi aktif: {lm.active_position_count}/{self.scheduler.config.max_concurrent_positions}")
        print(f"SOL deployed: {lm.total_sol_deployed:.3f} SOL")

        for addr, pos in lm.positions.items():
            status = "✅ IN RANGE" if pos.is_in_range else f"⚠️  OOR {pos.out_of_range_minutes:.0f}m"
            print(f"  • {pos.pool_name}: {pos.sol_deployed:.2f} SOL | "
                  f"Fee: {pos.fee_return_pct:.1f}% | {status}")

        if stats["total"] > 0:
            print(f"\n📈 History: {stats['total']} posisi | "
                  f"Win rate: {stats['win_rate']:.0f}% | "
                  f"Total fees: {stats['total_fees_sol']:.4f} SOL")
        print("="*50)

    def _print_thresholds(self):
        """Tampilkan threshold saat ini"""
        cfg = self.scheduler.config
        lessons = self.scheduler.lessons
        stats = lessons.get_performance_stats()

        print("\n🔧 SCREENING THRESHOLDS:")
        print(f"  Min organic score  : {cfg.min_organic_score}")
        print(f"  Min token holders  : {cfg.min_token_holders}")
        print(f"  Max volatility     : {cfg.max_pool_volatility}")
        print(f"  Max price change % : {cfg.max_price_change_pct}")
        print(f"  Max market cap     : ${cfg.max_market_cap_usd:,.0f}")
        print(f"  Take profit %      : {cfg.take_profit_pct}%")
        print(f"  OOR timeout        : {cfg.out_of_range_minutes} menit")

        if stats["total"] > 0:
            print(f"\n📊 PERFORMANCE (dari {stats['total']} posisi):")
            print(f"  Win rate           : {stats['win_rate']:.0f}%")
            print(f"  Avg return         : {stats['avg_return_pct']:.1f}%")
            print(f"  Avg duration       : {stats['avg_duration_min']:.0f} menit")

        suggestions = lessons.get_threshold_suggestions()
        if suggestions:
            print("\n💡 SARAN EVOLUSI:")
            for k, v in suggestions.items():
                print(f"  {k}: {v}")

    async def _handle_command(self, cmd: str):
        """Handle REPL command"""
        cmd = cmd.strip()

        if not cmd:
            return

        # Deploy manual berdasarkan nomor
        if cmd.isdigit():
            idx = int(cmd) - 1
            candidates = self.scheduler.state.state.last_candidates
            if 0 <= idx < len(candidates):
                pool_data = candidates[idx]
                print(f"🚀 Deploying ke pool #{cmd}: {pool_data.get('name', '?')}...")
                from pool_scanner import PoolInfo
                pool = PoolInfo(**{k: pool_data[k] for k in PoolInfo.__dataclass_fields__ if k in pool_data})
                pos = await self.scheduler.lp_manager.open_position(pool)
                if pos:
                    print(f"✅ Posisi dibuka: {pos.pool_name}")
                else:
                    print("❌ Gagal membuka posisi")
            else:
                print(f"❌ Nomor pool tidak valid. Ada {len(candidates)} kandidat.")
            return

        # /status
        if cmd == "/status":
            self._print_status()
            return

        # /candidates
        if cmd == "/candidates":
            print("🔍 Re-scanning pools...")
            await self.scheduler._scan_and_open()
            self._print_candidates()
            return

        # /learn
        if cmd.startswith("/learn"):
            parts = cmd.split(" ", 1)
            pool_addr = parts[1].strip() if len(parts) > 1 else None
            if pool_addr:
                pool_addrs = [pool_addr]
            else:
                pool_addrs = [c.get("address", "") for c in self.scheduler.state.state.last_candidates[:3]]

            if not pool_addrs or not any(pool_addrs):
                print("❌ Tidak ada pool untuk dipelajari. Jalankan /candidates dulu.")
                return

            print(f"📚 Mempelajari top LPers dari {len(pool_addrs)} pool...")
            lessons = await self.scheduler.top_lpers.study_and_save_lessons(
                pool_addrs, self.scheduler.llm
            )
            if lessons:
                print(f"💡 {len(lessons)} lessons baru disimpan:")
                for i, l in enumerate(lessons, 1):
                    print(f"  {i}. {l}")
            else:
                print("❌ Tidak ada lessons yang berhasil diekstrak")
            return

        # /evolve
        if cmd == "/evolve":
            stats = self.scheduler.lessons.get_performance_stats()
            if stats["total"] < 5:
                print(f"❌ Butuh minimal 5 posisi closed. Saat ini: {stats['total']}")
                return

            print("🧬 Menganalisis performance dan mengevolusi thresholds...")
            manual_sug = self.scheduler.lessons.get_threshold_suggestions()
            cfg_dict = {
                "min_organic_score": self.scheduler.config.min_organic_score,
                "min_token_holders": self.scheduler.config.min_token_holders,
                "take_profit_pct": self.scheduler.config.take_profit_pct,
                "out_of_range_minutes": self.scheduler.config.out_of_range_minutes,
            }
            result = await self.scheduler.llm.suggest_threshold_evolution(cfg_dict, stats, manual_sug)
            changes = result.get("changes", [])
            if changes:
                print(f"✅ {len(changes)} perubahan threshold disarankan:")
                for c in changes:
                    print(f"  {c['field']}: {c['old']} → {c['new']} ({c['reason']})")
                    # Apply ke config
                    if hasattr(self.scheduler.config, c["field"]):
                        setattr(self.scheduler.config, c["field"], c["new"])
                        self.scheduler.state.update_threshold(c["field"], c["new"], c["reason"])
                print("✅ Thresholds diperbarui!")
            else:
                print("Tidak ada perubahan yang disarankan saat ini.")
            return

        # /thresholds
        if cmd == "/thresholds":
            self._print_thresholds()
            return

        # /stop
        if cmd == "/stop":
            print("🛑 Menghentikan bot...")
            self.running = False
            self.scheduler._running = False
            return

        # /clear (clear chat history)
        if cmd == "/clear":
            self.scheduler.state.clear_chat_history()
            print("🗑️  Chat history dihapus")
            return

        # Free-form chat - kirim ke LLM
        positions_ctx = ""
        if self.scheduler.lp_manager.positions:
            pos_list = [p.to_dict() for p in self.scheduler.lp_manager.positions.values()]
            import json
            positions_ctx = f"\nPosisi aktif saat ini:\n{json.dumps(pos_list, indent=2)}"

        candidates_ctx = ""
        if self.scheduler.state.state.last_candidates:
            candidates_ctx = f"\nPool candidates terakhir: {len(self.scheduler.state.state.last_candidates)} pool"

        extra = positions_ctx + candidates_ctx
        print("🤖 Thinking...", end="", flush=True)
        response = await self.scheduler.llm.chat(cmd, extra_context=extra)
        print(f"\r🤖 {response}")

    async def run(self):
        """Jalankan REPL loop"""
        print("\n" + "="*60)
        print("🤖 MERIDIAN-ENHANCED LP BOT - Interactive REPL")
        print("="*60)
        print("Commands: /status, /candidates, /learn, /evolve, /thresholds, /stop")
        print("Ketik nomor (1,2,3) untuk deploy pool, atau chat bebas")
        print("="*60)

        loop = asyncio.get_event_loop()

        while self.running:
            try:
                prompt = self._get_prompt()
                # Non-blocking input
                cmd = await loop.run_in_executor(None, lambda: input(prompt))
                await self._handle_command(cmd)
            except EOFError:
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"REPL error: {e}")
