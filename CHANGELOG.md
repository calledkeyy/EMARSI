# Changelog

Semua perubahan penting pada proyek ini akan didokumentasikan di file ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.0.0/),
dan proyek ini menggunakan [Semantic Versioning](https://semver.org/lang/id/).

---

## [1.5.0] — 2026-05-07

### Changed — Format Display Signal

- `reports.py` — `signal_message()` beralih ke **MarkdownV2** dengan blockquote (`>`) untuk seluruh blok indikator:
  - RSI, MACD Hist, ADX, BB Pos, EMA, Volume, Momentum, ATR, OI, Funding Rate tampil dalam blockquote bertanda garis vertikal Telegram
  - Konstanta `SIGNAL_PARSE_MODE = "MarkdownV2"` diekspor untuk dipakai di handler
- `reports.py` — helper baru `_fmt_r_pnl(pnl: float) -> str`: format PNL sebagai R notation (`🟢 +1.00R` / `🔴 -1.00R`)
- `reports.py` — `tp_alert()` dan `sl_alert()` gunakan `_fmt_r_pnl()` — PNL ditampilkan dalam R, bukan %
- `reports.py` — `positions_message()` dan `_peak_analysis_block()` tampilkan peak dalam R
- `reports.py` — **Fix R:R** — baris `📊 R:R` sebelumnya menggunakan TP2 (2R), sekarang menggunakan TP3 (3R) sebagai target full close
- `reports.py` — **Score display disederhanakan** — dari `Bull X.X  Bear X.X` menjadi sisi dominan + edge: `Bull 8.5  (edge +5.5)` atau `Bear 7.0  (edge +4.0)`
- `telegram_handler.py` — `_send()` terima parameter `parse_mode` (default `"Markdown"` untuk backward compat)
- `telegram_handler.py` — `broadcast_signal()`, `cmd_signal()`, `cmd_scan()`, `cmd_topscan()` kirim signal message dengan `parse_mode=SIGNAL_PARSE_MODE`
- `telegram_handler.py` — `/history` tampilkan PNL dan peak dalam R notation
- `telegram_handler.py` — `/close` konfirmasi PNL dalam R notation

---

## [1.4.0] — 2026-05-06

### Added — Fitur 1: `/positions` Command
- `reports.py` — method baru `positions_message(rows: list) -> str`:
  - Tampilkan semua sinyal OPEN dengan entry, SL, TP1/TP2/TP3 beserta label R:R
  - Ikon `🔵` = executed trade, `⚪` = observation only
  - Tanda `✅` pada TP level yang sudah tercapai
  - Baris peak (`⛰️`) jika sudah ada peak_price di DB
  - Age sinyal (jam:menit sejak dibuat)
- `telegram_handler.py` — command `/positions`: fetch open signals, render `positions_message()`

### Added — Fitur 2: Format R:R di Signal Message
- `reports.py` — konstanta `DEFAULT_R_PCT = 1.5` dan helper `_pct_to_r(pct) -> str`
- `reports.py` — `signal_message()` ubah format SL/TP menjadi: `→ -1R`, `→ +1.0R`, `→ +2.0R`, `→ +3.0R  ← full close order`
- `reports.py` — `weekly_report()` dan `monthly_report()` tambah anotasi `(~±xR)` di avg/best/worst

### Added — Fitur 3: Flag Executed / Observation
- `database.py` — kolom `is_executed INTEGER DEFAULT 0` di tabel signals (auto-migrate)
- `database.py` — `mark_executed(signal_id, executed=True, year, month)`
- `telegram_handler.py` — command `/execute ID`: tandai sinyal sebagai executed trade
- `telegram_handler.py` — command `/unexecute ID`: kembalikan ke observation only
- `telegram_handler.py` — `/history` tampilkan ikon `🔵`/`⚪` dan summary executed vs observation

### Added — Fitur 4: Backtick Formatting Indikator
- `reports.py` — `signal_message()` semua nilai indikator pakai backtick: RSI, MACD Hist, ADX, BB Pos, EMA, Momentum, ATR, OI change, funding rate, volume ratio
- Volume anomaly: `\`4.2x avg\`` → 🔴 *Extreme Selling* CVD: `\`Bearish\`` `\`3\`` candles

### Added — Fitur 5: Peak Profit Tracking sebelum SL
- `database.py` — kolom `peak_price REAL`, `peak_tp_touched TEXT` di tabel signals (auto-migrate)
- `database.py` — `update_peak(signal_id, peak_price, peak_tp, year, month)`
- `database.py` — `get_peak_analysis(date_from, date_to) -> Dict`
- `scheduler.py` — `_check_open_signals()` update peak setiap 30 detik jika harga lebih menguntungkan
- `reports.py` — `sl_alert()` terima param `peak_price`, `peak_tp_touched`, `entry_price` dan tampilkan baris `⛰️ Peak`
- `reports.py` — `_peak_analysis_block(date_from, date_to)`: blok statistik peak untuk laporan
- `reports.py` — `daily_report()`, `weekly_report()`, `monthly_report()` sertakan peak analysis block

---

## [1.3.0] — 2026-05-06

### Added — Fitur 3: Volume Anomaly Detector
- `indicators.py` — `detect_volume_anomaly(volumes, closes, opens, period=20)`:
  - Deteksi spike volume vs rata-rata 20 candle sebelumnya
  - Strength: `extreme` (>5×), `high` (>3×), `moderate` (>2×), `normal`
  - Type: `buying_pressure` / `selling_pressure` / `normal`
  - CVD (Cumulative Volume Delta): `bullish` / `bearish` dari 10 candle terakhir
  - Consecutive: jumlah candle berturut-turut dengan volume > 1.5× rata-rata
- `signals.py` — scoring volume anomaly (step 5b, terpisah dari vol spike lama):
  - Extreme pressure: ±3 poin
  - High pressure: ±2 poin
  - Moderate pressure: ±1 poin
- `signals.py` — `SignalResult` tambah field `volume_anomaly: dict`
- `reports.py` — signal message tampilkan baris volume:
  `• Volume: 4.2x avg | 🔴 Extreme Selling | CVD: Bearish | 3 candles`
- `reports.py` — `signal_message()` tambah parameter opsional `source_label`

### Added — Fitur 4: Dynamic Top 30 Market Scan
- `fetcher.py` — `get_top30_by_volume()`: top 30 USDT-M pair by 24h volume, stablecoin excluded
- `database.py` — tabel `dynamic_watchlist` di `config.db` + 3 method baru:
  - `save_dynamic_watchlist(symbols, fetched_at)` — replace all + insert dengan rank
  - `get_dynamic_watchlist()` — return list symbol ORDER BY rank
  - `get_dynamic_watchlist_age()` — menit sejak last fetch (9999 jika kosong)
- `scheduler.py` — `_dynamic_scan_loop()`: loop baru paralel di `asyncio.gather`:
  - Refresh top 30 setiap 00/04/08/12/16/20 UTC + fallback jika age > 240 menit
  - Scan langsung setelah refresh, broadcast strong signals dengan label `[Top30 Scan]`
  - Berjalan terpisah dari `_auto_scan_loop` user watchlist
- `scheduler.py` — method publik `scan_top30(tf)` untuk trigger manual dari Telegram
- `telegram_handler.py` — command `/topscan [TF]`: manual scan top 30, tampilkan summary + kirim sinyal kuat
- `telegram_handler.py` — command `/toplist`: tampilkan daftar top 30 + waktu update terakhir & berikutnya

---

## [1.2.0] — 2026-05-06

### Changed — Fixed Risk:Reward Take Profit
- TP sekarang menggunakan fixed R:R, di mana R = jarak entry ke SL (= 1.5 × ATR)
  - TP1 = 1R = 1.5 × ATR (tidak berubah)
  - TP2 = 2R = 3.0 × ATR (sebelumnya 2.5 × ATR)
  - TP3 = 3R = 4.5 × ATR (sebelumnya 4.0 × ATR)
- SL tetap 1.5 × ATR, tidak ada perubahan

---

## [1.1.0] — 2026-05-06

### Added — Fitur 1: Open Interest (OI) Monitoring
- `fetcher.py` — `get_open_interest(symbol)`: ambil OI realtime via `/fapi/v1/openInterest`
- `fetcher.py` — `get_oi_history(symbol, period="5m", limit=12)`: 1 jam data OI via `/futures/data/openInterestHist`
- `indicators.py` — `calculate_oi_change(oi_history, price_change_pct)`:
  - Hitung % perubahan OI dalam 1 jam
  - Deteksi trend: `rising` / `falling` / `flat`
  - Signal: `bullish` (OI↑+harga↑), `bearish` (OI↑+harga↓), `weak_bullish` (OI↓+harga↑), `weak_bearish` (OI↓+harga↓)
  - Threshold: |oi_change_1h| > 2% untuk dianggap signifikan
- Scoring OI di `signals.py`: bullish/bearish +2, weak signals +1
- Signal message menampilkan: OI 1h change %, trend icon, dan signal label

### Added — Fitur 2: Funding Rate Agresif
- `fetcher.py` — `get_funding_rate_history(symbol, limit=8)`: history funding rate via `/fapi/v1/fundingRate`
- `indicators.py` — `calculate_funding_trend(funding_history)`: deteksi trend funding `rising` / `falling` / `stable`
- Scoring funding agresif di `signals.py`:
  - LONG + funding > +0.2% → bull_score −3 + `strong_warn` 🚨
  - LONG + funding > +0.1% → bull_score −2 + `warn` ⚠️
  - LONG + funding < −0.1% → bull_score +1 (kontra, bagus)
  - SHORT + funding < −0.2% → bear_score −3 + `strong_warn` 🚨
  - SHORT + funding < −0.1% → bear_score −2 + `warn` ⚠️
  - SHORT + funding > +0.1% → bear_score +1 (kontra, bagus)
- Signal message menampilkan: funding rate, level warning, trend icon
- `SignalResult` dataclass: tambah field `funding_level`, `funding_trend`, `oi_change_1h`, `oi_trend`, `oi_signal`
- `calculate_signal()`: parameter baru `oi_history` dan `funding_history`
- Fetch OI + funding history paralel (`asyncio.gather`) di `telegram_handler.py` dan `scheduler.py`

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
