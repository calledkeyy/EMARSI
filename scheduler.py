"""
scheduler.py — Background task scheduler
• Auto-scan watchlist at configured interval
• Real-time price monitoring for TP/SL/Invalidation
• Scheduled daily / weekly / monthly report broadcast
• Signal expiry checker
• Month-rollover DB creation
• Dynamic Top 30 scan (refreshed every 4 hours at 00/04/08/12/16/20 UTC)
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from config import AUTO_TRADE_ENABLED, TRADE_LEVERAGE
from database import DatabaseManager
from fetcher import BinanceFetcher
from signals import calculate_signal
from reports import ReportGenerator
from indicators import calculate_emas
from trader import BinanceTrader

if TYPE_CHECKING:
    from telegram_handler import TelegramBot

logger = logging.getLogger(__name__)


class BotScheduler:
    def __init__(self, db: DatabaseManager) -> None:
        self.db       = db
        self.fetcher  = BinanceFetcher()
        self.reports  = ReportGenerator(db)
        self.trader   = BinanceTrader()
        self.bot: Optional["TelegramBot"] = None   # injected after init
        self._running = False
        self._last_top30_key = ""  # "YYYYMMDDH" — prevents double-fire in same hour

    async def start(self) -> None:
        self._running = True
        await asyncio.gather(
            self._auto_scan_loop(),
            self._price_monitor_loop(),
            self._report_schedule_loop(),
            self._expiry_loop(),
            self._dynamic_scan_loop(),
            return_exceptions=True,
        )

    async def stop(self) -> None:
        self._running = False
        await self.fetcher.close()
        await self.trader.close()

    # ─────────────────────────────────────────────────────
    #  Auto-scan loop
    # ─────────────────────────────────────────────────────
    async def _auto_scan_loop(self) -> None:
        while self._running:
            try:
                if self.db.get_config("auto_scan", "true").lower() == "true":
                    await self._run_full_scan()
                interval = int(self.db.get_config("scan_interval", "300"))
                await asyncio.sleep(interval)
            except Exception as e:
                logger.exception("Auto-scan error: %s", e)
                await asyncio.sleep(60)

    async def _run_full_scan(self, tf: Optional[str] = None) -> list:
        """Scan all watchlist symbols. Returns list of SignalResult."""
        watchlist   = self.db.get_watchlist()
        tf          = tf or self.db.get_config("default_timeframe", "15m")
        min_conf    = int(self.db.get_config("min_confidence", "6"))
        expiry_h    = float(self.db.get_config("signal_expiry_hours", "4"))
        notify_lean = self.db.get_config("notify_lean", "false").lower() == "true"

        if not watchlist:
            return []

        logger.info("Scan started: %d pairs on %s", len(watchlist), tf)
        results = []

        for symbol in watchlist:
            try:
                klines = await self.fetcher.get_klines(symbol, tf, 200)
                if not klines:
                    continue

                funding, oi_hist, fund_hist = await asyncio.gather(
                    self.fetcher.get_funding_rate(symbol),
                    self.fetcher.get_oi_history(symbol),
                    self.fetcher.get_funding_rate_history(symbol),
                )
                rsi_hist = self.db.get_rsi_history(symbol, tf)

                sig = calculate_signal(
                    symbol=symbol, timeframe=tf,
                    opens=klines["opens"], highs=klines["highs"],
                    lows=klines["lows"],   closes=klines["closes"],
                    volumes=klines["volumes"],
                    funding_rate=funding, rsi_history=rsi_hist,
                    oi_history=oi_hist, funding_history=fund_hist,
                )
                self.db.save_rsi(symbol, tf, sig.rsi)
                results.append(sig)

                # Decide whether to save + notify
                is_strong = sig.signal_type in ("LONG", "SHORT") and sig.confidence >= min_conf
                is_lean   = sig.signal_type in ("LEAN_LONG", "LEAN_SHORT") and notify_lean and sig.confidence >= min_conf

                if is_strong or is_lean:
                    sid = self.db.save_signal(sig, expiry_h)
                    if self.bot:
                        await self.bot.broadcast_signal(sig, sid)

                    # Auto-execute: hanya sinyal kuat LONG/SHORT, bukan LEAN
                    if is_strong and AUTO_TRADE_ENABLED:
                        await self._auto_execute(sig, sid)

                await asyncio.sleep(0.15)   # gentle rate-limit

            except Exception as e:
                logger.error("Scan error %s: %s", symbol, e)

        logger.info("Scan finished: %d results", len(results))
        return results

    # ─────────────────────────────────────────────────────
    #  Price monitor loop  (TP / SL / Invalidation)
    # ─────────────────────────────────────────────────────
    async def _price_monitor_loop(self) -> None:
        while self._running:
            try:
                await self._check_open_signals()
                await asyncio.sleep(30)
            except Exception as e:
                logger.exception("Price monitor error: %s", e)
                await asyncio.sleep(30)

    async def _check_open_signals(self) -> None:
        open_signals = self.db.get_open_signals()
        if not open_signals:
            return

        # Fetch all prices in one API call to minimise requests
        all_prices = await self.fetcher.get_all_prices()
        tf         = self.db.get_config("default_timeframe", "15m")
        now        = datetime.now()

        for sig in open_signals:
            symbol = sig["symbol"]
            price  = all_prices.get(symbol, 0.0)
            if price == 0:
                continue

            sid    = sig["id"]
            s_type = sig["signal_type"]
            entry  = sig["entry_price"]
            sl     = sig["sl_price"]
            tp1    = sig["tp1_price"]
            tp2    = sig["tp2_price"]
            tp3    = sig["tp3_price"]

            # ── [FEATURE 5] Peak tracking ─────────────────────
            peak_px = sig.get("peak_price")
            peak_tp = sig.get("peak_tp_touched")

            try:
                if "LONG" in s_type:
                    pnl = (price - entry) / entry * 100

                    # Update peak if price moved more favourably
                    if peak_px is None or price > peak_px:
                        new_tp = None
                        if price >= tp3:
                            new_tp = "TP3"
                        elif price >= tp2:
                            new_tp = "TP2"
                        elif price >= tp1:
                            new_tp = "TP1"
                        self.db.update_peak(sid, price, new_tp, now.year, now.month)
                        peak_px, peak_tp = price, new_tp

                    if not sig["tp3_hit"] and price >= tp3:
                        self.db.update_signal_status(sid, "TP3", price, pnl)
                        await self._alert_tp(symbol, sid, "TP3", pnl)

                    elif not sig["tp2_hit"] and price >= tp2:
                        self.db.mark_tp_hit(sid, 2)
                        await self._alert_tp(symbol, sid, "TP2", pnl)

                    elif not sig["tp1_hit"] and price >= tp1:
                        self.db.mark_tp_hit(sid, 1)
                        await self._alert_tp(symbol, sid, "TP1", pnl)

                    elif price <= sl:
                        self.db.update_signal_status(sid, "SL", price, pnl)
                        await self._alert_sl(symbol, sid, pnl, peak_px, peak_tp, entry)

                    # Invalidation: EMA flipped bearish while in LONG
                    elif pnl < -3:
                        klines = await self.fetcher.get_klines(symbol, tf, 60)
                        if klines is not None:
                            e9, e21, e50 = calculate_emas(klines["closes"])
                            if e9 < e21 < e50:
                                self.db.invalidate_signal(sid, "EMA alignment turned bearish")
                                await self._alert_invalidated(symbol, sid, "EMA turned bearish")

                elif "SHORT" in s_type:
                    pnl = (entry - price) / entry * 100

                    # Update peak if price moved more favourably (lower = better for SHORT)
                    if peak_px is None or price < peak_px:
                        new_tp = None
                        if price <= tp3:
                            new_tp = "TP3"
                        elif price <= tp2:
                            new_tp = "TP2"
                        elif price <= tp1:
                            new_tp = "TP1"
                        self.db.update_peak(sid, price, new_tp, now.year, now.month)
                        peak_px, peak_tp = price, new_tp

                    if not sig["tp3_hit"] and price <= tp3:
                        self.db.update_signal_status(sid, "TP3", price, pnl)
                        await self._alert_tp(symbol, sid, "TP3", pnl)

                    elif not sig["tp2_hit"] and price <= tp2:
                        self.db.mark_tp_hit(sid, 2)
                        await self._alert_tp(symbol, sid, "TP2", pnl)

                    elif not sig["tp1_hit"] and price <= tp1:
                        self.db.mark_tp_hit(sid, 1)
                        await self._alert_tp(symbol, sid, "TP1", pnl)

                    elif price >= sl:
                        self.db.update_signal_status(sid, "SL", price, pnl)
                        await self._alert_sl(symbol, sid, pnl, peak_px, peak_tp, entry)

                    # Invalidation: EMA flipped bullish while in SHORT
                    elif pnl < -3:
                        klines = await self.fetcher.get_klines(symbol, tf, 60)
                        if klines is not None:
                            e9, e21, e50 = calculate_emas(klines["closes"])
                            if e9 > e21 > e50:
                                self.db.invalidate_signal(sid, "EMA alignment turned bullish")
                                await self._alert_invalidated(symbol, sid, "EMA turned bullish")

            except Exception as e:
                logger.error("Signal check error %s #%s: %s", symbol, sid, e)

    # ─────────────────────────────────────────────────────
    #  Alert helpers
    # ─────────────────────────────────────────────────────
    async def _alert_tp(self, symbol: str, sid: int, level: str, pnl: float) -> None:
        if self.bot:
            msg = self.reports.tp_alert(symbol, sid, level, pnl)
            await self.bot.broadcast_text(msg)

    async def _alert_sl(
        self,
        symbol: str,
        sid: int,
        pnl: float,
        peak_price: Optional[float] = None,
        peak_tp: Optional[str] = None,
        entry_price: Optional[float] = None,
    ) -> None:
        if self.bot:
            msg = self.reports.sl_alert(
                symbol, sid, pnl,
                peak_price=peak_price,
                peak_tp_touched=peak_tp,
                entry_price=entry_price,
            )
            await self.bot.broadcast_text(msg)

    async def _alert_invalidated(self, symbol: str, sid: int, reason: str) -> None:
        if self.bot:
            msg = self.reports.invalidation_alert(symbol, sid, reason)
            await self.bot.broadcast_text(msg)

    # ─────────────────────────────────────────────────────
    #  Scheduled report loop
    # ─────────────────────────────────────────────────────
    async def _report_schedule_loop(self) -> None:
        _sent: dict[str, bool] = {}   # prevent double-send within the same minute

        while self._running:
            now = datetime.now()
            key = now.strftime("%Y%m%d%H%M")

            if key not in _sent:
                # Daily report — 00:05
                if now.hour == 0 and now.minute == 5:
                    msg = "📊 *Auto Daily Report*\n\n" + self.reports.daily_report()
                    if self.bot:
                        await self.bot.broadcast_text(msg)
                    _sent[key] = True

                # Weekly report — Sunday 00:10
                elif now.weekday() == 6 and now.hour == 0 and now.minute == 10:
                    msg = "📊 *Auto Weekly Report*\n\n" + self.reports.weekly_report()
                    if self.bot:
                        await self.bot.broadcast_text(msg)
                    _sent[key] = True

                # Monthly report — 1st of month 00:15  (report for PREVIOUS month)
                elif now.day == 1 and now.hour == 0 and now.minute == 15:
                    py = now.year if now.month > 1 else now.year - 1
                    pm = now.month - 1 if now.month > 1 else 12
                    msg = "📊 *Auto Monthly Report*\n\n" + self.reports.monthly_report(py, pm)
                    if self.bot:
                        await self.bot.broadcast_text(msg)
                    # Create new month DB
                    self.db.ensure_month_db()
                    _sent[key] = True

            # Clean old keys (keep memory small)
            if len(_sent) > 10:
                oldest = sorted(_sent.keys())[0]
                del _sent[oldest]

            await asyncio.sleep(30)

    # ─────────────────────────────────────────────────────
    #  Expiry loop
    # ─────────────────────────────────────────────────────
    async def _expiry_loop(self) -> None:
        while self._running:
            try:
                expired_count = self.db.expire_old_signals()
                if expired_count:
                    logger.info("Expired %d old signal(s)", expired_count)
                await asyncio.sleep(60)
            except Exception as e:
                logger.error("Expiry loop error: %s", e)
                await asyncio.sleep(60)

    # ─────────────────────────────────────────────────────
    #  Dynamic Top 30 scan loop
    # ─────────────────────────────────────────────────────
    async def _dynamic_scan_loop(self) -> None:
        while self._running:
            try:
                await self._refresh_and_scan_top30()
                await asyncio.sleep(60)   # check every minute
            except Exception as e:
                logger.exception("Dynamic scan loop error: %s", e)
                await asyncio.sleep(60)

    async def _refresh_and_scan_top30(self) -> None:
        now_utc = datetime.utcnow()
        age     = self.db.get_dynamic_watchlist_age()

        # Schedule: 00, 04, 08, 12, 16, 20 UTC — or fallback if age > 4h
        on_schedule = (now_utc.hour % 4 == 0 and now_utc.minute == 0)
        hour_key    = f"{now_utc.strftime('%Y%m%d')}{now_utc.hour}"
        fresh_fire  = on_schedule and hour_key != self._last_top30_key
        stale       = age > 240   # >4 h — missed a schedule or first boot

        if not (fresh_fire or stale):
            return

        symbols = await self.fetcher.get_top30_by_volume()
        if not symbols:
            logger.warning("Top30 fetch returned empty list — skipping refresh")
            return

        self.db.save_dynamic_watchlist(symbols)
        self._last_top30_key = hour_key
        logger.info("Top30 refreshed (%d symbols), starting scan…", len(symbols))
        await self._scan_top30()

    async def _scan_top30(self, tf: Optional[str] = None) -> List:
        symbols  = self.db.get_dynamic_watchlist()
        if not symbols:
            return []

        tf       = tf or self.db.get_config("default_timeframe", "15m")
        min_conf = int(self.db.get_config("min_confidence", "6"))
        expiry_h = float(self.db.get_config("signal_expiry_hours", "4"))
        results  = []

        logger.info("Top30 scan: %d symbols on %s", len(symbols), tf)

        for symbol in symbols:
            try:
                klines = await self.fetcher.get_klines(symbol, tf, 200)
                if not klines:
                    continue

                funding, oi_hist, fund_hist = await asyncio.gather(
                    self.fetcher.get_funding_rate(symbol),
                    self.fetcher.get_oi_history(symbol),
                    self.fetcher.get_funding_rate_history(symbol),
                )
                rsi_hist = self.db.get_rsi_history(symbol, tf)

                sig = calculate_signal(
                    symbol=symbol, timeframe=tf,
                    opens=klines["opens"], highs=klines["highs"],
                    lows=klines["lows"],   closes=klines["closes"],
                    volumes=klines["volumes"],
                    funding_rate=funding, rsi_history=rsi_hist,
                    oi_history=oi_hist, funding_history=fund_hist,
                )
                self.db.save_rsi(symbol, tf, sig.rsi)
                results.append(sig)

                if sig.signal_type in ("LONG", "SHORT") and sig.confidence >= min_conf:
                    sid = self.db.save_signal(sig, expiry_h)
                    if self.bot:
                        msg = self.reports.signal_message(
                            sig, sid, source_label="Top30 Scan"
                        )
                        await self.bot.broadcast_text(msg)

                await asyncio.sleep(0.15)

            except Exception as e:
                logger.error("Top30 scan error %s: %s", symbol, e)

        logger.info("Top30 scan done: %d results", len(results))
        return results

    # ─────────────────────────────────────────────────────
    #  Auto-execute (Binance Demo)
    # ─────────────────────────────────────────────────────
    async def _auto_execute(self, sig, signal_id: int) -> None:
        """
        Eksekusi sinyal ke Binance Demo.
        - Side sama dengan posisi existing → averaging
        - Side berlawanan → skip (tidak flip otomatis)
        - Tidak ada posisi → open baru
        """
        symbol   = sig.symbol
        side     = "LONG" if "LONG" in sig.signal_type else "SHORT"
        risk_usd = float(self.db.get_config("trade_risk_usd", "5.0"))
        existing = self.db.get_open_trade(symbol)

        try:
            if existing:
                if existing["side"] != side:
                    logger.info(
                        "SKIP %s %s: ada posisi %s berlawanan — tidak flip otomatis",
                        side, symbol, existing["side"],
                    )
                    if self.bot:
                        await self.bot.broadcast_text(
                            f"⚠️ *Skip {symbol}*: sinyal {side} muncul tapi "
                            f"ada posisi {existing['side']} aktif.\n"
                            f"Gunakan /close {symbol} untuk menutup manual.",
                            parse_mode="Markdown",
                        )
                    return

                # Posisi sama → averaging
                logger.info("AVG %s %s (count=%d)", side, symbol, existing["avg_count"])
                result = await self.trader.add_to_position(
                    symbol=symbol,
                    side=side,
                    current_qty=existing["qty"],
                    current_entry=existing["entry_price"],
                    sl_price=existing["sl_price"],
                    new_tp3_price=sig.tp3_price,
                    old_tp_order_id=existing["tp_order_id"],
                    risk_usd=risk_usd,
                    leverage=existing["leverage"],
                )
                if not result:
                    return
                if result.get("skipped"):
                    if self.bot:
                        await self.bot.broadcast_text(
                            f"⚠️ *Skip averaging {symbol}*: "
                            f"margin dibutuhkan ${result['margin_required']:.2f}, "
                            f"available balance ${result['balance']:.2f}",
                            parse_mode="Markdown",
                        )
                    return

                self.db.update_trade_average(
                    symbol=symbol,
                    new_qty=result["new_qty"],
                    new_entry_price=result["avg_entry"],
                    new_tp3_price=sig.tp3_price,
                    new_tp_order_id=result["new_tp_order_id"],
                    signal_id=signal_id,
                )
                if self.bot:
                    await self.bot.broadcast_text(
                        f"📊 *Averaging {side} {symbol}* (ke-{existing['avg_count']+1})\n"
                        f"Entry avg: `${result['avg_entry']:,.4f}`\n"
                        f"Qty total: `{result['new_qty']}`\n"
                        f"TP3 baru: `${sig.tp3_price:,.4f}`\n"
                        f"SL: `${existing['sl_price']:,.4f}` (tidak berubah)\n"
                        f"Margin add-on: `${result['margin_used']:.2f}`",
                        parse_mode="Markdown",
                    )

            else:
                # Belum ada posisi → open baru
                result = await self.trader.open_position(
                    symbol=symbol,
                    side=side,
                    sl_price=sig.sl_price,
                    tp3_price=sig.tp3_price,
                    risk_usd=risk_usd,
                )
                if not result:
                    return
                if result.get("skipped"):
                    if self.bot:
                        await self.bot.broadcast_text(
                            f"⚠️ *Skip {symbol} {side}*: "
                            f"margin dibutuhkan ${result['margin_required']:.2f}, "
                            f"available balance ${result['balance']:.2f}",
                            parse_mode="Markdown",
                        )
                    return

                self.db.save_trade(
                    symbol=symbol,
                    side=side,
                    qty=result["qty"],
                    entry_price=result["entry_price"],
                    sl_price=sig.sl_price,
                    tp3_price=sig.tp3_price,
                    risk_usd=risk_usd,
                    leverage=TRADE_LEVERAGE,
                    sl_order_id=result["sl_order_id"],
                    tp_order_id=result["tp_order_id"],
                    signal_id=signal_id,
                )
                sl_pct = abs(result["entry_price"] - sig.sl_price) / result["entry_price"] * 100
                if self.bot:
                    await self.bot.broadcast_text(
                        f"✅ *Posisi dibuka: {side} {symbol}*\n"
                        f"Entry: `${result['entry_price']:,.4f}`\n"
                        f"Qty: `{result['qty']}`\n"
                        f"SL: `${sig.sl_price:,.4f}` ({sl_pct:.2f}%)\n"
                        f"TP3: `${sig.tp3_price:,.4f}`\n"
                        f"Margin: `${result['margin_used']:.2f}` | "
                        f"Max loss: `${risk_usd:.2f}`",
                        parse_mode="Markdown",
                    )

        except Exception as e:
            logger.exception("Auto-execute error %s: %s", symbol, e)

    # ─────────────────────────────────────────────────────
    #  Public — called from Telegram commands
    # ─────────────────────────────────────────────────────
    async def manual_scan(self, tf: Optional[str] = None) -> list:
        return await self._run_full_scan(tf)

    async def scan_top30(self, tf: Optional[str] = None) -> List:
        return await self._scan_top30(tf)
