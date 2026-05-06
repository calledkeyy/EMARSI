"""
reports.py — Message & report formatting
Signal alerts, daily / weekly / monthly reports, lifetime PNL
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import DatabaseManager

# ── [FEATURE 2] R constant — 1R = 1.5% (SL = 1.5 × ATR) ─────
DEFAULT_R_PCT: float = 1.5

# Parse mode required for signal_message (uses MarkdownV2 blockquotes)
SIGNAL_PARSE_MODE: str = "MarkdownV2"


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

# ── [FEATURE 2] Convert PNL % to R notation ──────────────────
def _pct_to_r(pct: float) -> str:
    if DEFAULT_R_PCT == 0:
        return ""
    r = pct / DEFAULT_R_PCT
    sign = "+" if r >= 0 else ""
    return f"  (~{sign}{r:.2f}R)"

def _fmt_r_pnl(pnl: float) -> str:
    """Format PNL as R notation for signal alerts (replaces %)."""
    if DEFAULT_R_PCT == 0:
        return _fmt_pnl(pnl)
    r = pnl / DEFAULT_R_PCT
    sign = "+" if r >= 0 else ""
    emoji = "🟢" if r >= 0 else "🔴"
    return f"{emoji} {sign}{r:.2f}R"

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

    # ── Signal alert (MarkdownV2 — blockquote for indicators) ──
    def signal_message(
        self, sig, signal_id: Optional[int] = None, source_label: str = ""
    ) -> str:
        st   = sig.signal_type
        icon = _SIGNAL_ICON.get(st, "⚪")
        ep   = sig.entry_price

        # ── [FEATURE 2] R:R multiplier labels ────────────
        R = abs(ep - sig.sl_price)
        def _rr(target: float) -> str:
            if R == 0:
                return "?R"
            v = round(abs(target - ep) / R, 1)
            return f"{v:.1f}R"
        tp3_rr_val = (abs(sig.tp3_price - ep) / R) if R > 0 else 3.0

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

        # Divergence — escape ! for MarkdownV2
        div_line = ""
        if sig.divergence == "bullish":
            div_line = "\n⚡ *Bullish Divergence Detected\\!*"
        elif sig.divergence == "bearish":
            div_line = "\n⚡ *Bearish Divergence Detected\\!*"

        # ── [FEATURE 4] OI — blockquote line ─────────────
        oi_line = ""
        if sig.oi_change_1h != 0.0 or sig.oi_trend != "flat":
            _oi_icon = {"rising": "📈", "falling": "📉", "flat": "➡️"}
            _oi_text = {
                "bullish": "Bullish", "bearish": "Bearish",
                "weak_bullish": "Weak Bullish", "weak_bearish": "Weak Bearish",
                "neutral": "Neutral",
            }
            sign    = "+" if sig.oi_change_1h >= 0 else ""
            oi_line = (
                f"\n> • OI \\(1h\\)     : `{sign}{sig.oi_change_1h:.2f}%`"
                f"  {_oi_icon.get(sig.oi_trend,'➡️')} {_oi_text.get(sig.oi_signal,'Neutral')}"
            )

        # ── [FEATURE 4] Funding — blockquote line ────────
        fr_line = ""
        if abs(sig.funding_rate) > 0.0001:
            _fr_icon = {"rising": "📈", "falling": "📉", "stable": "➡️"}
            if sig.funding_level == "strong_warn":
                fr_emoji, fr_tag = "🚨", " \\[EXTREME\\]"
            elif sig.funding_level == "warn":
                fr_emoji, fr_tag = "⚠️", " \\[HIGH\\]"
            else:
                fr_emoji, fr_tag = "ℹ️", ""
            fr_line = (
                f"\n> {fr_emoji} Funding      : `{sig.funding_rate * 100:.4f}%`"
                f"{fr_tag}  {_fr_icon.get(sig.funding_trend,'➡️')} {sig.funding_trend}"
            )

        # Source label — escape brackets for MarkdownV2
        src_line = f"🔍 *\\[{source_label}\\]*\n" if source_label else ""

        # ── [FEATURE 4] Volume — blockquote line ─────────
        va = sig.volume_anomaly or {}
        if va.get("anomaly"):
            _va_color    = {"buying_pressure": "🟢", "selling_pressure": "🔴"}.get(va.get("type",""), "⚪")
            _va_strength = va.get("strength", "").capitalize()
            _va_dir      = "Buying" if va.get("type") == "buying_pressure" else "Selling"
            _va_cvd      = va.get("cvd_trend", "").capitalize()
            _va_consec   = va.get("consecutive", 0)
            vol_display  = (
                f"• Volume      : `{va['ratio']:.1f}x avg`"
                f"  → {_va_color} *{_va_strength} {_va_dir}*"
                f"  CVD: `{_va_cvd}`  `{_va_consec}` candles"
            )
        else:
            vol_display = f"• Volume      : `{sig.volume_ratio:.2f}x avg`"

        if sig.bull_score >= sig.bear_score:
            score_line = f"⚖️  Score: Bull `{sig.bull_score:.1f}`  (edge `+{sig.bull_score - sig.bear_score:.1f}`)"
        else:
            score_line = f"⚖️  Score: Bear `{sig.bear_score:.1f}`  (edge `+{sig.bear_score - sig.bull_score:.1f}`)"

        return (
            f"{src_line}{icon} *{sig.symbol}  {sig.timeframe}  —  {st}*\n"
            f"{'─'*34}\n"
            f"🎯 Confidence: {_conf_bar(sig.confidence)}\n"
            f"{score_line}"
            f"{div_line}\n\n"
            f"💰 *Entry:*  `{_fmt_price(ep)}`\n"
            f"🛑 *SL:*     `{_fmt_price(sig.sl_price)}`  → `-1R`\n"
            f"🎁 *TP1:*   `{_fmt_price(sig.tp1_price)}`  → `+{_rr(sig.tp1_price)}`\n"
            f"🎁 *TP2:*   `{_fmt_price(sig.tp2_price)}`  → `+{_rr(sig.tp2_price)}`\n"
            f"🎁 *TP3:*   `{_fmt_price(sig.tp3_price)}`  → `+{_rr(sig.tp3_price)}`  ← full close order\n"
            f"📊 *R:R*     1:`{tp3_rr_val:.1f}`\n\n"
            f"📉 *Indicators*\n"
            f"> • RSI\\(14\\)     : `{sig.rsi:.1f}`\n"
            f"> • MACD Hist   : `{sig.macd_hist:+.6f}`\n"
            f"> • ADX         : `{sig.adx:.1f}`  → {adx_lbl}\n"
            f"> • BB Pos      : `{sig.bb_position:.2f}`  → {bb_lbl}\n"
            f"> • EMA 9/21/50 : {ema_lbl}\n"
            f"> {vol_display}\n"
            f"> • Momentum    : `{sig.momentum:+.2f}%`\n"
            f"> • ATR         : `{_fmt_price(sig.atr)}`"
            f"{oi_line}"
            f"{fr_line}\n\n"
            f"⏰ Expires in {self.db.get_config('signal_expiry_hours','4')}h"
            + (f"\n🆔 Signal ID: \\#{signal_id}" if signal_id else "")
        )

    # ── [FEATURE 1] Open positions list ──────────────────
    def positions_message(self, rows: list) -> str:
        if not rows:
            return "📋 *Open Positions*\n\nNo open signals at the moment."

        lines = [f"📋 *Open Positions*  ({len(rows)} open)", "═" * 32]

        for r in rows:
            icon    = _SIGNAL_ICON.get(r["signal_type"], "⚪")
            exec_ic = "🔵" if r.get("is_executed") else "⚪"
            ep      = r["entry_price"]
            sl      = r["sl_price"]
            tp1     = r["tp1_price"]
            tp2     = r["tp2_price"]
            tp3     = r["tp3_price"]

            R_val = abs(ep - sl) if sl else 0
            def _rr(t: float, _R: float = R_val, _ep: float = ep) -> str:
                if _R == 0:
                    return "?"
                return f"{abs(t - _ep) / _R:.1f}R"

            try:
                created = datetime.fromisoformat(r["created_at"])
                age     = datetime.now() - created
                h       = int(age.total_seconds() // 3600)
                m       = int((age.total_seconds() % 3600) // 60)
                age_str = f"{h}h {m}m"
            except Exception:
                age_str = "?"

            peak_line = ""
            if r.get("peak_price"):
                pp     = r["peak_price"]
                pp_pct = abs(pp - ep) / ep * 100 if ep else 0
                pp_r   = pp_pct / DEFAULT_R_PCT if DEFAULT_R_PCT else pp_pct
                tp_tag = f"  ← {r['peak_tp_touched']}" if r.get("peak_tp_touched") else ""
                peak_line = (
                    f"\n  ⛰️ Peak: {_fmt_price(pp)}"
                    f"  (`+{pp_r:.2f}R`){tp_tag}"
                )

            tp1_mark = "✅ " if r.get("tp1_hit") else "    "
            tp2_mark = "✅ " if r.get("tp2_hit") else "    "

            lines.append(
                f"\n{exec_ic} {icon} *{r['symbol']}*  —  {r['signal_type']}  ·  #{r['id']}\n"
                f"  ⏱ Age:  {age_str}  |  Conf: {r.get('confidence','?')}/10\n"
                f"  💰 Entry: {_fmt_price(ep)}\n"
                f"  🛑 SL:    {_fmt_price(sl)}  → `-1R`\n"
                f"  🎁 TP1:  {tp1_mark}{_fmt_price(tp1)}  → `+{_rr(tp1)}`\n"
                f"  🎁 TP2:  {tp2_mark}{_fmt_price(tp2)}  → `+{_rr(tp2)}`\n"
                f"  🎁 TP3:      {_fmt_price(tp3)}  → `+{_rr(tp3)}`  ← full close"
                f"{peak_line}"
            )

        lines.append(f"\n{'═'*32}\n🔵 = Executed trade  ⚪ = Observation only")
        return "\n".join(lines)

    # ── TP / SL / Invalidation alerts ────────────────────
    def tp_alert(self, symbol: str, signal_id: int, tp_level: str, pnl: float) -> str:
        return (
            f"🎯 *{tp_level} Hit!*\n\n"
            f"`{symbol}`  ·  #{signal_id}\n"
            f"PNL: {_fmt_r_pnl(pnl)}"
        )

    def sl_alert(
        self,
        symbol: str,
        signal_id: int,
        pnl: float,
        peak_price: Optional[float] = None,
        peak_tp_touched: Optional[str] = None,
        entry_price: Optional[float] = None,
    ) -> str:
        # ── [FEATURE 5] Show peak reached before SL ───────
        peak_line = ""
        if peak_price and entry_price:
            pp_pct = abs(peak_price - entry_price) / entry_price * 100
            pp_r   = pp_pct / DEFAULT_R_PCT if DEFAULT_R_PCT else pp_pct
            tp_tag = f"  ← peaked at {peak_tp_touched}" if peak_tp_touched else ""
            peak_line = (
                f"\n⛰️ Peak: {_fmt_price(peak_price)}"
                f"  (`+{pp_r:.2f}R`){tp_tag}"
            )

        return (
            f"🛑 *Stop Loss Triggered*\n\n"
            f"`{symbol}`  ·  #{signal_id}\n"
            f"PNL: {_fmt_r_pnl(pnl)}"
            f"{peak_line}"
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

        date_from = f"{date_str} 00:00:00"
        date_to   = f"{date_str} 23:59:59"
        peak_blk  = self._peak_analysis_block(date_from, date_to)

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
            f"{_fmt_pnl(pnl)}  *Total PNL*"
            f"{peak_blk}\n"
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

        now       = datetime.now()
        date_from = (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        date_to   = now.strftime("%Y-%m-%d %H:%M:%S")
        peak_blk  = self._peak_analysis_block(date_from, date_to)

        return (
            f"📊 *Weekly Report*\n"
            f"{'═'*32}\n\n"
            f"📡 Signals: {total}\n"
            f"✅ {wins}W  ❌ {losses}L  ⏰ {expired} expired\n\n"
            f"🎯 *Win Rate: {wr:.1f}%*\n"
            f"{_win_bar(wr)}\n\n"
            f"{_fmt_pnl(pnl)}  *Total PNL*\n"
            f"📊 Avg / trade:  {avg_pnl:+.2f}%{_pct_to_r(avg_pnl)}\n"
            f"🏆 Best trade:   +{best:.2f}%{_pct_to_r(best)}\n"
            f"💔 Worst trade:  {worst:.2f}%{_pct_to_r(worst)}"
            f"{peak_blk}\n"
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
        date_from = f"{year}-{month:02d}-01 00:00:00"
        import calendar
        last_day  = calendar.monthrange(year, month)[1]
        date_to   = f"{year}-{month:02d}-{last_day:02d} 23:59:59"
        peak_blk  = self._peak_analysis_block(date_from, date_to)

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
            f"📊 Avg / trade:  {avg_pnl:+.2f}%{_pct_to_r(avg_pnl)}\n"
            f"🏆 Best trade:   +{best:.2f}%{_pct_to_r(best)}\n"
            f"💔 Worst trade:  {worst:.2f}%{_pct_to_r(worst)}\n\n"
            f"📅 All months: `{months_available}`"
            f"{peak_blk}\n"
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

    # ── [FEATURE 5] Peak analysis block ──────────────────
    def _peak_analysis_block(self, date_from: str, date_to: str) -> str:
        data = self.db.get_peak_analysis(date_from, date_to)
        if not data or not data.get("total_with_peaks"):
            return ""
        total    = data.get("total_with_peaks", 0)
        tp1_r    = data.get("tp1_reached", 0)
        tp2_r    = data.get("tp2_reached", 0)
        avg_p    = data.get("avg_peak_pct", 0.0)
        sl_aft1  = data.get("sl_after_tp1", 0)
        sl_aft2  = data.get("sl_after_tp2", 0)
        return (
            f"\n⛰️ *Peak Analysis (SL trades):*\n"
            f"  → TP1 reached before SL: {tp1_r}/{total}"
            + (f"  ({sl_aft1} closed at SL after TP1)" if sl_aft1 else "")
            + f"\n  → TP2 reached before SL: {tp2_r}/{total}"
            + (f"  ({sl_aft2} closed at SL after TP2)" if sl_aft2 else "")
            + f"\n  → Avg peak: `{avg_p / DEFAULT_R_PCT if DEFAULT_R_PCT else avg_p:+.2f}R`"
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
