# 🤖 Trading Signal Bot — Binance Futures USDT-M

Bot Telegram untuk sinyal trading Binance Futures dengan analisis teknikal multi-indikator,
laporan harian/mingguan/bulanan, dan tracking PNL seumur hidup.

---

## ✨ Fitur

| Fitur | Detail |
|---|---|
| **Indikator** | RSI(14), MACD, Bollinger Bands, EMA 9/21/50, Volume Ratio, Momentum, ADX, ATR |
| **Sinyal** | LONG / SHORT / LEAN / NEUTRAL dengan confidence 1-10 |
| **SL/TP** | Otomatis berbasis ATR (1.5x / 2.5x / 4.0x) |
| **Divergence** | Deteksi bullish/bearish RSI divergence |
| **Invalidation** | Auto-invalidate saat EMA flip + PNL < -3% |
| **Funding Rate** | Peringatan jika funding > 0.1% |
| **Fear & Greed** | Index real-time dari alternative.me |
| **Database** | SQLite rotating per bulan + lifetime PNL |
| **Laporan** | Harian (00:05), Mingguan (Minggu 00:10), Bulanan (tgl 1 00:15) |
| **Win Rate** | Per symbol dari seluruh history |

---

## 🚀 Instalasi

### 1. Clone / download project
```bash
git clone <repo> trading_bot
cd trading_bot
```

### 2. Buat virtual environment
```bash
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Setup environment
```bash
cp .env.example .env
nano .env   # isi TELEGRAM_TOKEN dan ALLOWED_CHAT_IDS
```

### 5. Jalankan bot
```bash
python main.py
```

---

## ⚙️ Konfigurasi via Telegram

| Perintah | Fungsi |
|---|---|
| `/settf 15m` | Set timeframe default |
| `/setconfig` | Lihat semua setting |
| `/setconfig min_confidence 7` | Ubah min confidence |
| `/setconfig scan_interval 180` | Scan tiap 3 menit |
| `/setconfig signal_expiry_hours 6` | Sinyal expired setelah 6 jam |
| `/setconfig notify_lean true` | Notif sinyal LEAN juga |
| `/pause` / `/resume` | Toggle auto-scan |

**Timeframe valid:** `1m 3m 5m 15m 30m 1h 2h 4h 6h 12h 1d`

---

## 📊 Command Reference

```
/start               — Status bot
/help                — Daftar command
/signal BTCUSDT      — Analisa pair
/signal ETHUSDT 1h   — Analisa pair dengan TF custom
/scan                — Scan semua watchlist
/scan 4h             — Scan dengan TF custom

/addpair SOLUSDT     — Tambah pair
/removepair SOLUSDT  — Hapus pair
/watchlist           — Lihat semua pair

/report daily        — Laporan hari ini
/report weekly       — Laporan 7 hari
/report monthly      — Laporan bulan ini
/report monthly 2025-01  — Laporan bulan tertentu

/pnl                 — Lifetime PNL
/pnl BTCUSDT         — PNL per symbol
/winrate             — Win rate per symbol
/history             — 10 sinyal terakhir
/history 20          — N sinyal terakhir

/close 42 TP2        — Manual close sinyal #42 sebagai TP2
/close 42 SL -2.3    — Manual close dengan PNL custom

/status              — Status + Fear & Greed live
/pause               — Pause auto-scan
/resume              — Resume auto-scan
/setconfig           — Lihat/edit config
```

---

## 📁 Struktur File

```
trading_bot/
├── main.py              ← Entry point
├── config.py            ← Environment & constants
├── indicators.py        ← Semua kalkulasi indikator
├── signals.py           ← Scoring engine & signal generation
├── database.py          ← SQLite manager (monthly rotate + lifetime)
├── fetcher.py           ← Binance Futures API client
├── reports.py           ← Format pesan & laporan
├── scheduler.py         ← Background tasks
├── telegram_handler.py  ← Semua command Telegram
├── requirements.txt
├── .env.example
└── data/                ← Auto-created
    ├── config.db        ← Watchlist, config, RSI history
    ├── lifetime.db      ← Semua closed trades
    ├── signals_2025_01.db
    └── signals_2025_02.db  ← Monthly rotating
```

---

## 🔢 Sistem Scoring

| Indikator | Kondisi | Poin |
|---|---|---|
| RSI | < 30 | Bull +3 |
| RSI | < 40 / < 45 | Bull +2 / +1 |
| RSI | > 70 | Bear +3 |
| RSI | > 60 / > 55 | Bear +2 / +1 |
| MACD | Bullish + hist > 0 | Bull +2 |
| MACD | Bearish + hist < 0 | Bear +2 |
| EMA | 9 > 21 > 50 | Bull +3 |
| EMA | 9 < 21 < 50 | Bear +3 |
| BB | Position < 0.2 | Bull +2 |
| BB | Position > 0.8 | Bear +2 |
| Volume | > 2x avg + green | Bull +1 |
| Volume | > 2x avg + red | Bear +1 |
| Momentum | > +2% | Bull +1 |
| Momentum | < -2% | Bear +1 |
| ADX | > 25 (trending) | +0.5 sisi dominan |
| ADX | < 20 (ranging) | -0.5 kedua sisi |
| Divergence | Bullish RSI div | Bull +3 |
| Divergence | Bearish RSI div | Bear +3 |
| Funding | > 0.1% vs arah | -1 sisi berlawanan |

**Signal:** Bull ≥ 3 && diff ≥ 1 → LONG | Bear ≥ 3 && diff ≤ -1 → SHORT | lainnya → LEAN / NEUTRAL

---

## 📝 Catatan

- Bot hanya monitor **Binance Futures USDT-M**
- Semua data disimpan lokal di folder `data/`
- Database baru otomatis dibuat setiap awal bulan
- Expired signals otomatis sync ke lifetime PNL

---

## 🛡️ Disclaimer

Bot ini hanya untuk tujuan edukasi dan informasi.
Bukan saran finansial. Trading memiliki risiko tinggi.
Selalu gunakan risk management yang baik.
