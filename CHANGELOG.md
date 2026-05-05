# Changelog

Semua perubahan penting pada proyek ini akan didokumentasikan di file ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.0.0/),
dan proyek ini menggunakan [Semantic Versioning](https://semver.org/lang/id/).

---

## [1.0.0] — 2026-05-06

### Added
- **Bot Telegram** lengkap untuk sinyal trading Binance Futures USDT-M
- **Engine Indikator** multi-indikator:
  - RSI(14) dengan smoothing Wilder
  - MACD (12/26/9)
  - Bollinger Bands (20 period, 2σ)
  - EMA 9 / 21 / 50
  - Volume Ratio vs rata-rata 20 candle
  - Momentum (perubahan harga %)
  - ADX (Average Directional Index)
  - ATR (Average True Range)
- **Sistem Scoring** bull/bear dengan bobot per indikator:
  - RSI oversold/overbought: ±1 hingga ±3 poin
  - MACD crossover + histogram: ±2 poin
  - EMA alignment (9>21>50 atau 9<21<50): ±3 poin
  - Bollinger Band position: ±2 poin
  - Volume spike konfirmasi: ±1 poin
  - Momentum: ±1 poin
  - ADX trending/ranging modifier: ±0.5 poin
  - RSI Divergence bullish/bearish: ±3 poin
  - Funding Rate penalty: -1 poin berlawanan arah
- **Tipe Sinyal**: LONG / SHORT / LEAN\_LONG / LEAN\_SHORT / NEUTRAL dengan confidence 1–10
- **SL/TP otomatis** berbasis ATR (1.5× / 2.5× / 4.0×)
- **Deteksi RSI Divergence** bullish dan bearish
- **Auto-invalidation** sinyal saat EMA flip atau PNL < -3%
- **Monitoring Funding Rate** Binance Futures dengan peringatan jika > 0.1%
- **Fear & Greed Index** real-time dari alternative.me
- **Database SQLite** dengan rotasi bulanan otomatis + lifetime PNL tracking
- **Laporan terjadwal**: harian (00:05), mingguan (Minggu 00:10), bulanan (tgl 1 00:15)
- **Win rate tracking** per symbol dari seluruh history
- **Manual close** sinyal dengan outcome TP1 / TP2 / TP3 / SL / custom PNL
- **Watchlist dinamis**: tambah/hapus pair via command Telegram
- **Konfigurasi runtime** via `/setconfig` tanpa restart bot:
  - `min_confidence` — threshold confidence minimum sinyal
  - `scan_interval` — interval auto-scan (detik)
  - `signal_expiry_hours` — masa berlaku sinyal
  - `notify_lean` — toggle notifikasi sinyal LEAN
- **Command Telegram** lengkap:
  - `/signal`, `/scan` — analisa on-demand
  - `/report daily|weekly|monthly` — laporan performa
  - `/pnl`, `/winrate`, `/history` — statistik trading
  - `/addpair`, `/removepair`, `/watchlist` — manajemen pair
  - `/pause`, `/resume` — toggle auto-scan
  - `/status` — status bot + Fear & Greed live
- **Multi-timeframe**: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d

### Dependencies
- `python-telegram-bot==20.7`
- `aiohttp==3.9.5`
- `numpy==1.26.4`
- `python-dotenv==1.0.1`
