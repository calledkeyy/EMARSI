"""
telegram_handler.py — Telegram bot command handlers
All /commands and inline callbacks
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import TELEGRAM_TOKEN, ALLOWED_CHAT_IDS, VALID_TIMEFRAMES
from database import DatabaseManager
from fetcher import BinanceFetcher
from signals import calculate_signal
from reports import ReportGenerator

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, db: DatabaseManager, scheduler=None) -> None:
        self.db        = db
        self.fetcher   = BinanceFetcher()
        self.reports   = ReportGenerator(db)
        self.scheduler = scheduler
        self.app: Optional[Application] = None

    # ─────────────────────────────────────────────────────
    #  Auth
    # ─────────────────────────────────────────────────────
    def _ok(self, update: Update) -> bool:
        if not ALLOWED_CHAT_IDS:
            return True
        return update.effective_chat.id in ALLOWED_CHAT_IDS

    # ─────────────────────────────────────────────────────
    #  Start / setup
    # ─────────────────────────────────────────────────────
    async def start(self) -> None:
        self.app = Application.builder().token(TELEGRAM_TOKEN).build()

        cmds = [
            ("start",       self.cmd_start),
            ("help",        self.cmd_help),
            ("signal",      self.cmd_signal),
            ("scan",        self.cmd_scan),
            ("addpair",     self.cmd_add_pair),
            ("removepair",  self.cmd_remove_pair),
            ("watchlist",   self.cmd_watchlist),
            ("settf",       self.cmd_set_tf),
            ("setconfig",   self.cmd_setconfig),
            ("report",      self.cmd_report),
            ("pnl",         self.cmd_pnl),
            ("winrate",     self.cmd_winrate),
            ("status",      self.cmd_status),
            ("pause",       self.cmd_pause),
            ("resume",      self.cmd_resume),
            ("close",       self.cmd_close),
            ("history",     self.cmd_history),
        ]
        for name, handler in cmds:
            self.app.add_handler(CommandHandler(name, handler))

        self.app.add_handler(CallbackQueryHandler(self._on_callback))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot is polling…")
        await asyncio.Event().wait()   # block forever

    # ─────────────────────────────────────────────────────
    #  Broadcast helpers
    # ─────────────────────────────────────────────────────
    async def broadcast_text(self, text: str) -> None:
        for chat_id in (ALLOWED_CHAT_IDS or []):
            await self._send(chat_id, text)

    async def broadcast_signal(self, sig, signal_id: int) -> None:
        msg = self.reports.signal_message(sig, signal_id)
        await self.broadcast_text(msg)

    async def _send(self, chat_id: int, text: str, markup=None) -> None:
        if not self.app:
            return
        try:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error("send_message to %s: %s", chat_id, e)

    # ─────────────────────────────────────────────────────
    #  /start
    # ─────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        tf        = self.db.get_config("default_timeframe", "15m")
        watchlist = self.db.get_watchlist()
        auto      = self.db.get_config("auto_scan", "true")

        await update.message.reply_text(
            f"🤖 *Trading Signal Bot — Active*\n"
            f"{'━'*32}\n\n"
            f"📡 *Config*\n"
            f"• Timeframe : {tf}\n"
            f"• Watchlist : {len(watchlist)} pairs\n"
            f"• Market    : Binance Futures USDT-M\n"
            f"• Auto-scan : {auto}\n\n"
            f"*Quick start:*\n"
            f"/signal BTCUSDT — instant signal\n"
            f"/scan            — scan watchlist\n"
            f"/settf 1h        — change timeframe\n"
            f"/help            — all commands",
            parse_mode="Markdown",
        )

    # ─────────────────────────────────────────────────────
    #  /help
    # ─────────────────────────────────────────────────────
    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        await update.message.reply_text(
            "📖 *Command Reference*\n"
            "{'━'*32}\n\n"
            "*📊 Signals*\n"
            "/signal `SYM` `[TF]`  — analyse pair\n"
            "/scan `[TF]`           — scan watchlist\n\n"
            "*👁 Watchlist*\n"
            "/addpair `SYM`        — add pair\n"
            "/removepair `SYM`     — remove pair\n"
            "/watchlist            — show list\n\n"
            "*⚙️ Config*\n"
            "/settf `TF`           — set default timeframe\n"
            "  Valid: 1m 3m 5m 15m 30m 1h 2h 4h 6h 12h 1d\n"
            "/setconfig            — show / edit settings\n"
            "/setconfig `key` `val` — change setting\n\n"
            "*📈 Reports*\n"
            "/report daily\n"
            "/report weekly\n"
            "/report monthly `[YYYY-MM]`\n\n"
            "*💰 PNL*\n"
            "/pnl `[SYM]`         — lifetime PNL\n"
            "/winrate             — win rate by symbol\n"
            "/history             — last 10 signals\n\n"
            "*🔧 Control*\n"
            "/pause  — stop auto-scan\n"
            "/resume — start auto-scan\n"
            "/status — bot status\n"
            "/close `ID` `STATUS`  — close signal manually\n"
            "  Status: TP1 TP2 TP3 SL EXPIRED",
            parse_mode="Markdown",
        )

    # ─────────────────────────────────────────────────────
    #  /signal
    # ─────────────────────────────────────────────────────
    async def cmd_signal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        if not ctx.args:
            await update.message.reply_text(
                "Usage: /signal BTCUSDT [timeframe]\nExample: /signal ETHUSDT 1h"
            )
            return

        symbol = ctx.args[0].upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        tf = (ctx.args[1].lower() if len(ctx.args) > 1
              else self.db.get_config("default_timeframe", "15m"))

        if tf not in VALID_TIMEFRAMES:
            await update.message.reply_text(
                f"❌ Invalid timeframe: `{tf}`\n"
                f"Valid: {', '.join(VALID_TIMEFRAMES)}",
                parse_mode="Markdown",
            )
            return

        loading = await update.message.reply_text(f"🔍 Analysing `{symbol}` on `{tf}`…", parse_mode="Markdown")

        try:
            klines = await self.fetcher.get_klines(symbol, tf, 200)
            if not klines:
                await loading.edit_text(f"❌ No data for `{symbol}`. Is it listed on Binance Futures?", parse_mode="Markdown")
                return

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

            signal_id = None
            min_conf  = int(self.db.get_config("min_confidence", "6"))
            if sig.signal_type != "NEUTRAL" and sig.confidence >= min_conf:
                expiry = float(self.db.get_config("signal_expiry_hours", "4"))
                signal_id = self.db.save_signal(sig, expiry)

            msg = self.reports.signal_message(sig, signal_id)
            await loading.edit_text(msg, parse_mode="Markdown")

        except Exception as e:
            logger.exception("cmd_signal error: %s", e)
            await loading.edit_text(f"❌ Error: {e}")

    # ─────────────────────────────────────────────────────
    #  /scan
    # ─────────────────────────────────────────────────────
    async def cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        tf = (ctx.args[0].lower() if ctx.args
              else self.db.get_config("default_timeframe", "15m"))

        if tf not in VALID_TIMEFRAMES:
            await update.message.reply_text(f"❌ Invalid timeframe: {tf}")
            return

        watchlist = self.db.get_watchlist()
        if not watchlist:
            await update.message.reply_text("⚠️ Watchlist is empty. Use /addpair BTCUSDT")
            return

        loading = await update.message.reply_text(
            f"🔍 Scanning {len(watchlist)} pairs on *{tf}*…", parse_mode="Markdown"
        )

        results = await self.scheduler.manual_scan(tf)

        summary = self.reports.scan_summary(results, tf)
        await loading.edit_text(summary, parse_mode="Markdown")

        # Send individual strong signals to chat
        chat_id = update.effective_chat.id
        strong  = [s for s in results if s.signal_type in ("LONG", "SHORT")
                   and s.confidence >= int(self.db.get_config("min_confidence", "6"))]
        for sig in sorted(strong, key=lambda x: x.confidence, reverse=True)[:5]:
            msg = self.reports.signal_message(sig)
            await self._send(chat_id, msg)
            await asyncio.sleep(0.5)

    # ─────────────────────────────────────────────────────
    #  /addpair  /removepair  /watchlist
    # ─────────────────────────────────────────────────────
    async def cmd_add_pair(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        if not ctx.args:
            await update.message.reply_text("Usage: /addpair BTCUSDT"); return

        symbol = ctx.args[0].upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        loading = await update.message.reply_text(f"🔍 Validating `{symbol}`…", parse_mode="Markdown")
        valid   = await self.fetcher.validate_symbol(symbol)

        if not valid:
            await loading.edit_text(f"❌ `{symbol}` not found on Binance Futures.", parse_mode="Markdown")
            return

        self.db.add_to_watchlist(symbol)
        n = len(self.db.get_watchlist())
        await loading.edit_text(f"✅ `{symbol}` added to watchlist  ({n} total)", parse_mode="Markdown")

    async def cmd_remove_pair(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        if not ctx.args:
            await update.message.reply_text("Usage: /removepair BTCUSDT"); return

        symbol = ctx.args[0].upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        self.db.remove_from_watchlist(symbol)
        await update.message.reply_text(f"✅ `{symbol}` removed from watchlist.", parse_mode="Markdown")

    async def cmd_watchlist(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        wl = self.db.get_watchlist()
        if not wl:
            await update.message.reply_text("📋 Watchlist is empty.\n\n/addpair BTCUSDT"); return
        pairs = "\n".join(f"• `{s}`" for s in wl)
        await update.message.reply_text(
            f"📋 *Watchlist ({len(wl)} pairs)*\n\n{pairs}\n\n"
            "_/addpair SYM  |  /removepair SYM_",
            parse_mode="Markdown",
        )

    # ─────────────────────────────────────────────────────
    #  /settf
    # ─────────────────────────────────────────────────────
    async def cmd_set_tf(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        if ctx.args:
            tf = ctx.args[0].lower()
            if tf not in VALID_TIMEFRAMES:
                await update.message.reply_text(f"❌ Invalid. Valid: {', '.join(VALID_TIMEFRAMES)}"); return
            self.db.set_config("default_timeframe", tf)
            await update.message.reply_text(f"✅ Default timeframe → *{tf}*", parse_mode="Markdown")
            return

        # Interactive keyboard
        current = self.db.get_config("default_timeframe", "15m")
        rows = [
            [InlineKeyboardButton(t, callback_data=f"tf_{t}") for t in VALID_TIMEFRAMES[i:i+4]]
            for i in range(0, len(VALID_TIMEFRAMES), 4)
        ]
        await update.message.reply_text(
            f"⏱ Current timeframe: *{current}*\n\nSelect new timeframe:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    # ─────────────────────────────────────────────────────
    #  /setconfig
    # ─────────────────────────────────────────────────────
    _CONFIG_KEYS = {
        "default_timeframe":   "Default TF (e.g. 15m)",
        "scan_interval":       "Scan interval in seconds",
        "min_confidence":      "Min confidence to save signal (1-10)",
        "signal_expiry_hours": "Signal expiry in hours",
        "auto_scan":           "Auto scan: true / false",
        "notify_lean":         "Notify LEAN signals: true / false",
        "leverage_suggestion": "Suggested leverage (info only)",
        "risk_per_trade_pct":  "Risk per trade %",
    }

    async def cmd_setconfig(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        if ctx.args and len(ctx.args) >= 2:
            key, val = ctx.args[0], ctx.args[1]
            if key not in self._CONFIG_KEYS:
                await update.message.reply_text(
                    f"❌ Unknown key: `{key}`\n"
                    f"Valid keys: {', '.join(self._CONFIG_KEYS.keys())}",
                    parse_mode="Markdown",
                )
                return
            self.db.set_config(key, val)
            await update.message.reply_text(f"✅ `{key}` = `{val}`", parse_mode="Markdown")
            return

        lines = ["⚙️ *Bot Configuration*", "━" * 30]
        for k, desc in self._CONFIG_KEYS.items():
            v = self.db.get_config(k, "—")
            lines.append(f"• `{k}`: `{v}`  _{desc}_")
        lines.append("\n_Change: /setconfig key value_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ─────────────────────────────────────────────────────
    #  /report
    # ─────────────────────────────────────────────────────
    async def cmd_report(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        rtype = (ctx.args[0].lower() if ctx.args else "daily")

        if rtype == "daily":
            msg = self.reports.daily_report()
        elif rtype == "weekly":
            msg = self.reports.weekly_report()
        elif rtype == "monthly":
            if len(ctx.args) > 1:
                try:
                    y, m = map(int, ctx.args[1].split("-"))
                    msg = self.reports.monthly_report(y, m)
                except Exception:
                    msg = "❌ Format: /report monthly YYYY-MM"
            else:
                msg = self.reports.monthly_report()
        else:
            msg = "Usage: /report [daily | weekly | monthly] [YYYY-MM]"

        await update.message.reply_text(msg, parse_mode="Markdown")

    # ─────────────────────────────────────────────────────
    #  /pnl
    # ─────────────────────────────────────────────────────
    async def cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        symbol = None
        if ctx.args:
            symbol = ctx.args[0].upper()
            if not symbol.endswith("USDT"):
                symbol += "USDT"
        msg = self.reports.lifetime_pnl(symbol)
        await update.message.reply_text(msg, parse_mode="Markdown")

    # ─────────────────────────────────────────────────────
    #  /winrate
    # ─────────────────────────────────────────────────────
    async def cmd_winrate(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        data = self.db.get_win_rate_by_symbol()
        if not data:
            await update.message.reply_text("📊 No closed trades yet."); return

        lines = ["🏆 *Win Rate by Symbol — Lifetime*", "━" * 30]
        for i, r in enumerate(data[:15], 1):
            bar_n  = int(r["win_rate"] / 10)
            bar    = "🟩" * bar_n + "⬜" * (10 - bar_n)
            sign   = "+" if r["total_pnl"] >= 0 else ""
            lines.append(
                f"\n*{i}. {r['symbol']}*\n"
                f"   {bar} {r['win_rate']}%\n"
                f"   ✅ {r['wins']}W  ❌ {r['losses']}L  |  PNL: {sign}{r['total_pnl']:.2f}%"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ─────────────────────────────────────────────────────
    #  /status
    # ─────────────────────────────────────────────────────
    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        open_sigs = self.db.get_open_signals()
        wl        = self.db.get_watchlist()
        months    = self.db.get_available_months()
        tf        = self.db.get_config("default_timeframe", "15m")
        auto      = self.db.get_config("auto_scan", "true")
        interval  = self.db.get_config("scan_interval", "300")
        conf      = self.db.get_config("min_confidence", "6")
        fg        = await self.fetcher.get_fear_greed()

        await update.message.reply_text(
            f"🤖 *Bot Status*\n"
            f"{'━'*30}\n"
            f"🟢 Running — {datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
            f"⚙️ *Config*\n"
            f"• Timeframe:    {tf}\n"
            f"• Auto-scan:    {auto}  (every {interval}s)\n"
            f"• Min Conf:     {conf}/10\n\n"
            f"📊 *Data*\n"
            f"• Open signals: {len(open_sigs)}\n"
            f"• Watchlist:    {len(wl)} pairs\n"
            f"• DB months:    {len(months)}\n\n"
            f"😨 *Fear & Greed:* {fg['value']} — {fg['label']}\n\n"
            f"_/pause  /resume  /setconfig_",
            parse_mode="Markdown",
        )

    # ─────────────────────────────────────────────────────
    #  /pause  /resume
    # ─────────────────────────────────────────────────────
    async def cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        self.db.set_config("auto_scan", "false")
        await update.message.reply_text("⏸ Auto-scan *paused*.\nUse /resume to restart.", parse_mode="Markdown")

    async def cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        self.db.set_config("auto_scan", "true")
        await update.message.reply_text("▶️ Auto-scan *resumed*.", parse_mode="Markdown")

    # ─────────────────────────────────────────────────────
    #  /close  (manual outcome recording)
    # ─────────────────────────────────────────────────────
    _VALID_CLOSE = {"TP1", "TP2", "TP3", "SL", "EXPIRED", "INVALIDATED"}
    _PNL_MAP     = {"TP1": 1.5, "TP2": 2.5, "TP3": 4.0,
                    "SL": -1.5, "EXPIRED": 0.0, "INVALIDATED": 0.0}

    async def cmd_close(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return
        if not ctx.args or len(ctx.args) < 2:
            await update.message.reply_text(
                "Usage: /close SIGNAL_ID STATUS\nStatus: TP1 TP2 TP3 SL EXPIRED"
            ); return

        try:
            sid    = int(ctx.args[0])
            status = ctx.args[1].upper()
        except ValueError:
            await update.message.reply_text("❌ Invalid signal ID"); return

        if status not in self._VALID_CLOSE:
            await update.message.reply_text(
                f"❌ Invalid status. Use: {', '.join(self._VALID_CLOSE)}"
            ); return

        # Optional custom PNL as 3rd arg
        pnl = self._PNL_MAP[status]
        if len(ctx.args) >= 3:
            try:
                pnl = float(ctx.args[2])
            except ValueError:
                pass

        self.db.update_signal_status(sid, status, 0.0, pnl)
        sign = "+" if pnl >= 0 else ""
        await update.message.reply_text(
            f"✅ Signal *#{sid}* → *{status}*\nPNL recorded: {sign}{pnl:.2f}%",
            parse_mode="Markdown",
        )

    # ─────────────────────────────────────────────────────
    #  /history
    # ─────────────────────────────────────────────────────
    async def cmd_history(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._ok(update): return

        limit = 10
        if ctx.args:
            try: limit = int(ctx.args[0])
            except ValueError: pass

        rows = self.db.get_recent_signals(limit)
        if not rows:
            await update.message.reply_text("No signals this month."); return

        lines = [f"📜 *Last {limit} Signals*", "━" * 30]
        for r in rows:
            st_icon  = _STATUS_ICON.get(r["status"], "❓")
            sig_icon = "🟢" if "LONG" in r["signal_type"] else "🔴"
            pnl_str  = (f"  {'+' if r['pnl_pct'] >= 0 else ''}{r['pnl_pct']:.2f}%"
                        if r["status"] not in ("OPEN", "EXPIRED") else "")
            lines.append(
                f"\n`#{r['id']}` {sig_icon} `{r['symbol']}` {r['timeframe']}  "
                f"{st_icon} *{r['status']}*{pnl_str}\n"
                f"   _Conf {r['confidence']}/10  ·  {r['created_at'][:16]}_"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ─────────────────────────────────────────────────────
    #  Callback handler
    # ─────────────────────────────────────────────────────
    async def _on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q    = update.callback_query
        data = q.data
        await q.answer()

        if data.startswith("tf_"):
            tf = data[3:]
            self.db.set_config("default_timeframe", tf)
            await q.edit_message_text(f"✅ Timeframe set to *{tf}*", parse_mode="Markdown")


# ── Re-export status icon for other modules ──────────────────
_STATUS_ICON = {
    "OPEN":        "⏳",
    "TP1":         "✅",
    "TP2":         "✅✅",
    "TP3":         "✅✅✅",
    "SL":          "❌",
    "EXPIRED":     "⏰",
    "INVALIDATED": "⚠️",
}
