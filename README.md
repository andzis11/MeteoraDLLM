# 🤖 Meteora LP Bot 
Bot otomatis untuk Liquidity Provider di **Meteora DLMM** (Solana), diperkuat dengan arsitektur dari Meridian.

---

## ✨ Fitur

| Fitur | Keterangan |
|---|---|
| 🎯 **Hunter Alpha** | Scan & filter pool terbaik setiap 30 menit |
| 🩺 **Healer Alpha** | Kelola posisi aktif setiap 10 menit |
| 🤖 **MiniMax LLM** | ReAct reasoning (THINK → ANALYZE → DECIDE) |
| 📱 **Telegram 2-arah** | Notifikasi + chat langsung via bot Telegram |
| 💻 **Interactive REPL** | CLI dengan countdown timer + deploy manual |
| 📚 **Learning System** | Pelajari top LPers, simpan lessons, evolusi threshold |
| 💾 **Persistent State** | State, history, lessons tersimpan antar restart |
| ⛓️ **Real Transactions** | Transaksi on-chain via Solana (+ mode simulasi) |

---

## 📁 Struktur File

```
meteora_lp_bot/
├── main.py              # Entry point
├── config.py            # Konfigurasi bot
├── scheduler.py         # Orchestrator: Hunter + Healer + REPL + Telegram
│
├── pool_scanner.py      # Scan & filter pool Meteora DLMM
├── lp_manager.py        # Buka/tutup posisi LP (real + simulasi)
├── meteora_client.py    # RPC & Meteora API client
├── tx_builder.py        # Builder transaksi Solana on-chain
├── token_helper.py      # Utilitas token (wrap SOL, ATA, dll)
│
├── llm_advisor.py       # Hunter & Healer Alpha (MiniMax ReAct)
├── lessons.py           # Learning system & performance history
├── state_manager.py     # Persistent state antar restart
├── top_lpers.py         # Analisis strategi top LPers
│
├── repl.py              # Interactive CLI dengan countdown timer
├── telegram_notifier.py # Telegram notif + 2-arah chat
│
├── requirements.txt     # Python dependencies
├── .env.example         # Template environment variables
└── .gitignore
```

---

## 🚀 Setup

### 1. Clone & Install
```bash
git clone https://github.com/andzis11/meteora-lp-bot.git
cd meteora-lp-bot
pip install -r requirements.txt
```

### 2. Konfigurasi `.env`
```bash
cp .env.example .env
# Edit .env dan isi semua nilai
```

### 3. Jalankan
```bash
# Mode simulasi (aman, tidak ada transaksi nyata)
DRY_RUN=true python main.py

# Mode live
python main.py
```

---

## ⚙️ Environment Variables

| Variable | Keterangan |
|---|---|
| `WALLET_PRIVATE_KEY` | Private key Solana (base58) |
| `RPC_URL` | Solana RPC URL (default: Helius) |
| `MINIMAX_API_KEY` | API key MiniMax ([api.minimax.io](https://api.minimax.io)) |
| `TELEGRAM_BOT_TOKEN` | Token bot Telegram (dari @BotFather) |
| `TELEGRAM_CHAT_ID` | Chat ID (opsional, bot auto-detect) |

---

## 💻 REPL Commands

Setelah bot jalan, prompt interaktif tersedia:

```
[manage: 8m 30s | screen: 22m 00s]
> 
```

| Command | Keterangan |
|---|---|
| `1`, `2`, `3` | Deploy ke pool kandidat nomor tersebut |
| `/status` | Status bot, posisi aktif, balance |
| `/candidates` | Re-scan dan tampilkan top pool |
| `/learn` | Pelajari top LPers dari pool kandidat |
| `/learn <pool_address>` | Pelajari top LPers dari pool spesifik |
| `/thresholds` | Lihat threshold saat ini + performance stats |
| `/evolve` | Evolusi threshold dari data performance (min 5 posisi) |
| `/stop` | Graceful shutdown |
| `<teks apapun>` | Chat bebas dengan AI agent |

---

## 📱 Telegram Commands

Kirim pesan ke bot Telegram kamu:

| Command | Keterangan |
|---|---|
| `/start` | Lihat semua commands |
| `/status` | Status bot & posisi |
| `/candidates` | Pool terbaik saat ini |
| `/learn` | Pelajari top LPers |
| `/thresholds` | Lihat threshold |
| `/evolve` | Evolusi threshold |
| `<teks apapun>` | Chat bebas dengan AI |

> **Auto-register**: Cukup kirim pesan pertama ke bot, chat ID akan otomatis terdaftar.

---

## 🧠 Learning System

Bot secara otomatis belajar dari pengalaman:

### `/learn` — Pelajari Top LPers
Analisis on-chain behavior LP terbaik di pool target: hold duration, win rate, pola entry/exit. Lessons disimpan ke `lessons.json` dan diinjeksi ke setiap prompt LLM.

### `/evolve` — Evolusi Threshold
Setelah 5+ posisi ditutup, bot menganalisis performance dan menyesuaikan filter otomatis (organic score, holder count, take profit, dll).

---

## ⚙️ Konfigurasi (config.py)

| Parameter | Default | Keterangan |
|---|---|---|
| `sol_per_position` | 0.3 | SOL per posisi LP |
| `max_concurrent_positions` | 2 | Maks posisi bersamaan |
| `min_organic_score` | 75 | Filter token spam |
| `min_token_holders` | 500 | Filter token baru |
| `max_price_change_pct` | 200 | Filter pump extrem |
| `take_profit_pct` | 15.0 | Target profit (%) |
| `out_of_range_minutes` | 10 | Tutup jika OOR berapa menit |
| `management_cycle_minutes` | 5 | Interval Healer Alpha |
| `screening_cycle_minutes` | 15 | Interval Hunter Alpha |

---

## ⚠️ Disclaimer

Software ini disediakan apa adanya tanpa garansi. Menjalankan bot trading otomatis membawa risiko finansial nyata — kamu bisa kehilangan dana. Selalu mulai dengan mode simulasi (`DRY_RUN=true`) sebelum live. Jangan deploy lebih dari yang kamu siap kehilangan. Ini bukan financial advice.

