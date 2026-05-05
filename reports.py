"""
reports.py — Message & report formatting
Signal alerts, daily / weekly / monthly reports, lifetime PNL
"""
from __future__ import annotations
from datetime import datetime
from typing import Dict, Optional

from database import DatabaseManager


# ─────────────────────────────────────────────────────────────
#  Small helpers
# ─────────────────────────────────────────────────────────────
def _fmt_price(p: float) -> str:
    if p >= 1_000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    return f"${p:.6f}"

def _fmt_pnl(pnl: float) -> str:
    sign  = "+" if pnl >= 0 else ""
    emoji = "🟢" if pnl >= 0 else "🔴"
    return f"{emoji} {sign}{pnl:.2f}%"

def _conf_bar(conf: int) -> str:
    return "█" * conf + "░" * (10 - conf) + f" {conf}/10"

def _win_bar(win_rate: float) -> str:
    filled = int(win_rate / 10)
    return "🟩" * filled + "⬜" * (10 - filled)

_SIGNAL_ICON = {
    "LONG":       "🟢",
    "SHORT":      "🔴",
    "LEAN_LONG":  "🟡",
    "LEAN_SHORT": "🟠",
    "NEUTRAL":    "⚪",
}

_STATUS_ICON = {
    "OPEN":        "⏳",
    "TP1":         "✅",
    "TP2":         "✅✅",
    "TP3":         "✅✅✅",
    "SL":          "❌",
    "EXPIRED":     "⏰",
    "INVALIDATED": "⚠️",
}


# ─────────────────────────────────────────────────────────────
#  ReportGenerator
# ─────────────────────────────────────────────────────────────
class ReportGenerator:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    # ── Signal alert ─────────────────────────────────────
    def signal_message(self, sig, signal_id: Optional[int] = None) -> str:
        st   = sig.signal_type
        icon = _SIGNAL_ICON.get(st, "⚪")
        ep   = sig.entry_price

        # Percentage distances
        def pct(target: float) -> str:
            if ep == 0:
                return "0.00%"
            return f"{abs((target - ep) / ep * 100):.2f}%"

        # R:R
        risk   = abs(ep - sig.sl_price)
        reward = abs(sig.tp2_price - ep)
        rr     = reward / risk if risk else 0

        # EMA label
        if sig.ema9 > sig.ema21 > sig.ema50:
            ema_lbl = "📈 Bullish"
        elif sig.ema9 < sig.ema21 < sig.ema50:
            ema_lbl = "📉 Bearish"
        else:
            ema_lbl = "🔀 Mixed"

        # ADX label
        if sig.adx >= 25:
            adx_lbl = "📈 Trending"
        elif sig.adx >= 20:
            adx_lbl = "〰️ Weak"
        else:
            adx_lbl = "⚠️ Ranging"

        # BB label
        if sig.bb_position < 0.3:
            bb_lbl = "Near Lower 🔼"
        elif sig.bb_position > 0.7:
            bb_lbl = "Near Upper 🔽"
        else:
            bb_lbl = "Middle"

        # Divergence
        div_line = ""
        if sig.divergence == "bullish":
            div_line = "\n⚡ *Bullish Divergence Detected!*"
        elif sig.divergence == "bearish":
            div_line = "\n⚡ *Bearish Divergence Detected!*"

        # OI section
        oi_line = ""
        if sig.oi_change_1h != 0.0 or sig.oi_trend != "flat":
            _oi_trend_icon = {"rising": "📈", "falling": "📉", "flat": "➡️"}
            _oi_sig_text = {
                "bullish":      "Bullish",
                "bearish":      "Bearish",
                "weak_bullish": "Weak Bullish",
                "weak_bearish": "Weak Bearish",
                "neutral":      "Neutral",
            }
            t_icon   = _oi_trend_icon.get(sig.oi_trend, "➡️")
            sig_text = _oi_sig_text.get(sig.oi_signal, "Neutral")
            sign     = "+" if sig.oi_change_1h >= 0 else ""
            oi_line  = f"\n• OI (1h):    {sign}{sig.oi_change_1h:.2f}%  {t_icon} {sig_text}"

        # Funding rate section — agresif
        fr_line = ""
        if abs(sig.funding_rate) > 0.0001:
            _fr_trend_icon = {"rising": "📈", "falling": "📉", "stable": "➡️"}
            if sig.funding_level == "strong_warn":
                fr_emoji = "🚨"
                fr_tag   = " [EXTREME]"
            elif sig.funding_level == "warn":
                fr_emoji = "⚠️"
                fr_tag   = " [HIGH]"
            else:
                fr_emoji = "ℹ️"
                fr_tag   = ""
            tr_icon = _fr_trend_icon.get(sig.funding_trend, "➡️")
            fr_line = (
                f"\n{fr_emoji} Funding: {sig.funding_rate * 100:.4f}%"
                f"{fr_tag}  {tr_icon} {sig.funding_trend}"
            )

        return (
            f"{icon} *{sig.symbol}  {sig.timeframe}  —  {st}*\n"
            f"{'─'*34}\n"
            f"🎯 Confidence: {_conf_bar(sig.confidence)}\n"
            f"⚖️  Score: Bull {sig.bull_score:.1f}  Bear {sig.bear_score:.1f}"
            f"{div_line}\n\n"
            f"💰 *Entry:*  {_fmt_price(ep)}\n"
            f"🛑 *SL:*     {_fmt_price(sig.sl_price)}  ({pct(sig.sl_price)})\n"
            f"🎁 *TP1:*   {_fmt_price(sig.tp1_price)}  (+{pct(sig.tp1_price)})\n"
            f"🎁 *TP2:*   {_fmt_price(sig.tp2_price)}  (+{pct(sig.tp2_price)})\n"
            f"🎁 *TP3:*   {_fmt_price(sig.tp3_price)}  (+{pct(sig.tp3_price)})\n"
            f"📊 *R:R*     1:{rr:.1f}\n\n"
            f"📉 *Indicators*\n"
            f"• RSI(14):    {sig.rsi:.1f}\n"
            f"• MACD Hist:  {sig.macd_hist:+.6f}\n"
            f"• ADX:        {sig.adx:.1f}  {adx_lbl}\n"
            f"• BB Pos:     {sig.bb_position:.2f}  ({bb_lbl})\n"
            f"• EMA 9/21/50: {ema_lbl}\n"
            f"• Volume:     {sig.volume_ratio:.2f}x avg\n"
            f"• Momentum:   {sig.momentum:+.2f}%\n"
            f"• ATR:        {_fmt_price(sig.atr)}"
            f"{oi_line}"
            f"{fr_line}\n\n"
            f"⏰ Expires in {self.db.get_config('signal_expiry_hours','4')}h"
            + (f"\n🆔 Signal ID: #{signal_id}" if signal_id else "")
        )

    # ── TP / SL / Invalidation alerts ────────────────────
    def tp_alert(self, symbol: str, signal_id: int, tp_level: str, pnl: float) -> str:
        return (
            f"🎯 *{tp_level} Hit!*\n\n"
            f"`{symbol}`  ·  #{signal_id}\n"
            f"PNL: {_fmt_pnl(pnl)}"
        )

    def sl_alert(self, symbol: str, signal_id: int, pnl: float) -> str:
        return (
            f"🛑 *Stop Loss Triggered*\n\n"
            f"`{symbol}`  ·  #{signal_id}\n"
            f"PNL: {_fmt_pnl(pnl)}"
        )

    def invalidation_alert(self, symbol: str, signal_id: int, reason: str) -> str:
        return (
            f"⚠️ *Signal Invalidated*\n\n"
            f"`{symbol}`  ·  #{signal_id}\n"
            f"Reason: {reason}"
        )

    # ── Daily report ─────────────────────────────────────
    def daily_report(self, date_str: Optional[str] = None) -> str:
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        s = self.db.get_daily_stats(date_str)
        if not s or not s.get("total"):
            return f"📊 *Daily Report — {date_str}*\n\nNo signals today."

        total  = s["total"]    or 0
        wins   = s["wins"]     or 0
        losses = s["losses"]   or 0
        expired= s["expired"]  or 0
        open_c = s["open_count"] or 0
        pnl    = s["total_pnl"]  or 0.0
        syms   = s["symbols_traded"] or 0
        closed = wins + losses
        wr     = wins / closed * 100 if closed else 0

        return (
            f"📊 *Daily Report — {date_str}*\n"
            f"{'═'*32}\n\n"
            f"📡 Signals Generated: {total}\n"
            f"🏷  Symbols Traded:    {syms}\n\n"
            f"✅ Wins:    {wins}\n"
            f"❌ Losses:  {losses}\n"
            f"⏳ Open:    {open_c}\n"
            f"⏰ Expired: {expired}\n"
            f"🎯 Win Rate: {wr:.1f}%\n\n"
            f"{_fmt_pnl(pnl)}  *Total PNL*\n"
            f"{'═'*32}\n"
            f"_Generated {datetime.now():%H:%M:%S}_"
        )

    # ── Weekly report ─────────────────────────────────────
    def weekly_report(self) -> str:
        s = self.db.get_weekly_stats()
        if not s or not s.get("total"):
            return "📊 *Weekly Report*\n\nNo closed signals this week."

        total   = s["total"]    or 0
        wins    = s["wins"]     or 0
        losses  = s["losses"]   or 0
        expired = s["expired"]  or 0
        pnl     = s["total_pnl"] or 0.0
        avg_pnl = s["avg_pnl"]  or 0.0
        best    = s["best_trade"]  or 0.0
        worst   = s["worst_trade"] or 0.0
        closed  = wins + losses
        wr      = wins / closed * 100 if closed else 0

        return (
            f"📊 *Weekly Report*\n"
            f"{'═'*32}\n\n"
            f"📡 Signals: {total}\n"
            f"✅ {wins}W  ❌ {losses}L  ⏰ {expired} expired\n\n"
            f"🎯 *Win Rate: {wr:.1f}%*\n"
            f"{_win_bar(wr)}\n\n"
            f"{_fmt_pnl(pnl)}  *Total PNL*\n"
            f"📊 Avg / trade:  {avg_pnl:+.2f}%\n"
            f"🏆 Best trade:   +{best:.2f}%\n"
            f"💔 Worst trade:  {worst:.2f}%\n"
            f"{'═'*32}\n"
            f"_Generated {datetime.now():%Y-%m-%d %H:%M}_"
        )

    # ── Monthly report ────────────────────────────────────
    def monthly_report(self, year: Optional[int] = None, month: Optional[int] = None) -> str:
        now   = datetime.now()
        year  = year  or now.year
        month = month or now.month
        label = datetime(year, month, 1).strftime("%B %Y")
        s     = self.db.get_monthly_stats(year, month)

        if not s or not s.get("total"):
            return f"📊 *Monthly Report — {label}*\n\nNo data for this period."

        total   = s["total"]    or 0
        wins    = s["wins"]     or 0
        losses  = s["losses"]   or 0
        expired = s["expired"]  or 0
        open_c  = s["open_count"] or 0
        pnl     = s["total_pnl"]  or 0.0
        avg_pnl = s["avg_pnl"]    or 0.0
        best    = s["best_trade"]  or 0.0
        worst   = s["worst_trade"] or 0.0
        closed  = wins + losses
        wr      = wins / closed * 100 if closed else 0

        months_available = ", ".join(self.db.get_available_months()) or "none"

        return (
            f"📊 *Monthly Report — {label}*\n"
            f"{'═'*32}\n\n"
            f"📡 Total Signals: {total}\n"
            f"✅ Wins:    {wins}\n"
            f"❌ Losses:  {losses}\n"
            f"⏳ Open:    {open_c}\n"
            f"⏰ Expired: {expired}\n"
            f"🎯 Win Rate: {wr:.1f}%\n"
            f"{_win_bar(wr)}\n\n"
            f"{_fmt_pnl(pnl)}  *Total PNL*\n"
            f"📊 Avg / trade:  {avg_pnl:+.2f}%\n"
            f"🏆 Best trade:   +{best:.2f}%\n"
            f"💔 Worst trade:  {worst:.2f}%\n\n"
            f"📅 All months: `{months_available}`\n"
            f"{'═'*32}\n"
            f"_Generated {datetime.now():%Y-%m-%d %H:%M}_"
        )

    # ── Lifetime PNL ──────────────────────────────────────
    def lifetime_pnl(self, symbol: Optional[str] = None) -> str:
        s    = self.db.get_lifetime_stats(symbol)
        syms = self.db.get_win_rate_by_symbol()

        if not s or not s.get("total"):
            return "📊 *Lifetime PNL*\n\nNo closed trades yet."

        total  = s["total"]     or 0
        wins   = s["wins"]      or 0
        losses = s["losses"]    or 0
        pnl    = s["total_pnl"] or 0.0
        avg    = s["avg_pnl"]   or 0.0
        best   = s["best_trade"]  or 0.0
        worst  = s["worst_trade"] or 0.0
        closed = wins + losses
        wr     = wins / closed * 100 if closed else 0

        # Top symbols section
        top_block = ""
        if syms and not symbol:
            lines = ["\n\n🏆 *Top Symbols (Win Rate):*"]
            for i, r in enumerate(syms[:7], 1):
                lines.append(
                    f"{i}. `{r['symbol']}` "
                    f"{r['win_rate']}%  "
                    f"({r['wins']}W/{r['losses']}L)  "
                    f"{_fmt_pnl(r['total_pnl'])}"
                )
            top_block = "\n".join(lines)

        title = f"Lifetime PNL — {symbol}" if symbol else "Lifetime PNL"
        months = ", ".join(self.db.get_available_months()) or "none"

        return (
            f"📊 *{title}*\n"
            f"{'═'*32}\n\n"
            f"📡 Total Trades: {total}\n"
            f"✅ Wins:   {wins}  ❌ Losses: {losses}\n"
            f"🎯 Win Rate: {wr:.1f}%\n"
            f"{_win_bar(wr)}\n\n"
            f"{_fmt_pnl(pnl)}  *Total PNL*\n"
            f"📊 Avg / trade:  {avg:+.2f}%\n"
            f"🏆 Best:   +{best:.2f}%\n"
            f"💔 Worst:   {worst:.2f}%\n\n"
            f"📅 Months: `{months}`"
            f"{top_block}"
        )

    # ── Scan summary ─────────────────────────────────────
    def scan_summary(self, results: list, tf: str) -> str:
        longs    = [s for s in results if "LONG"  in s.signal_type]
        shorts   = [s for s in results if "SHORT" in s.signal_type]
        strong   = [s for s in results if s.signal_type in ("LONG","SHORT")]

        lines = [
            f"🔍 *Scan Complete — {tf}*",
            f"{'━'*32}",
            f"📊 Pairs Scanned: {len(results)}",
            f"🟢 Bullish signals: {len(longs)}",
            f"🔴 Bearish signals: {len(shorts)}",
            f"⚡ Strong (LONG/SHORT): {len(strong)}",
        ]

        if strong:
            lines.append("\n*🎯 Strong Signals:*")
            for s in sorted(strong, key=lambda x: x.confidence, reverse=True):
                icon = "🟢" if s.signal_type == "LONG" else "🔴"
                lines.append(
                    f"{icon} `{s.symbol}` — {s.signal_type}  "
                    f"Conf: {s.confidence}/10  RSI: {s.rsi:.0f}  ADX: {s.adx:.0f}"
                )
        else:
            lines.append("\n_No strong signals found in this scan_")

        return "\n".join(lines)
