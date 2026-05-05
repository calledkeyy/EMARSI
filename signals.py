"""
signals.py — Core signal engine
Scoring system, signal determination, SL/TP calculation
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from indicators import (
    calculate_rsi, calculate_macd, calculate_bollinger,
    calculate_emas, calculate_volume_ratio, calculate_momentum,
    calculate_adx, calculate_atr, detect_divergence,
    calculate_oi_change, calculate_funding_trend,
    detect_volume_anomaly,
)


# ─────────────────────────────────────────────────────────────
#  Signal Result dataclass
# ─────────────────────────────────────────────────────────────
@dataclass
class SignalResult:
    symbol: str
    timeframe: str
    signal_type: str          # LONG | SHORT | LEAN_LONG | LEAN_SHORT | NEUTRAL
    confidence: int           # 1–10
    bull_score: float
    bear_score: float

    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    tp3_price: float

    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    adx: float

    ema9: float
    ema21: float
    ema50: float

    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_position: float

    volume_ratio: float
    momentum: float
    divergence: str

    funding_rate: float
    funding_warning: bool
    funding_level: str      # "ok" | "warn" | "strong_warn"
    funding_trend: str      # "rising" | "falling" | "stable"

    oi_change_1h: float     # % OI change over last 1h
    oi_trend: str           # "rising" | "falling" | "flat"
    oi_signal: str          # "bullish" | "bearish" | "weak_bullish" | "weak_bearish" | "neutral"

    atr: float

    volume_anomaly: dict  = field(default_factory=dict)
    score_breakdown: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
#  Main signal calculation
# ─────────────────────────────────────────────────────────────
def calculate_signal(
    symbol: str,
    timeframe: str,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    funding_rate: float = 0.0,
    rsi_history: Optional[list[float]] = None,
    oi_history: Optional[list] = None,
    funding_history: Optional[list] = None,
) -> SignalResult:

    # ── Calculate all indicators ──────────────────────────
    rsi                         = calculate_rsi(closes)
    macd, macd_sig, macd_hist   = calculate_macd(closes)
    bb_up, bb_mid, bb_lo, bb_pos = calculate_bollinger(closes)
    ema9, ema21, ema50          = calculate_emas(closes)
    vol_ratio                   = calculate_volume_ratio(volumes)
    momentum                    = calculate_momentum(closes)
    adx                         = calculate_adx(highs, lows, closes)
    atr                         = calculate_atr(highs, lows, closes)

    divergence = "none"
    if rsi_history and len(rsi_history) >= 10:
        divergence = detect_divergence(closes, rsi_history)

    # OI analysis — use momentum as price-direction proxy
    oi_raw     = calculate_oi_change(oi_history or [], price_change_pct=momentum)
    oi_change_1h = oi_raw["oi_change_1h"]
    oi_trend     = oi_raw["oi_trend"]
    oi_signal    = oi_raw["signal"]

    # Funding trend
    funding_trend = calculate_funding_trend(funding_history or [])

    # Volume anomaly
    vol_anom = detect_volume_anomaly(volumes, closes, opens)

    is_green = float(closes[-1]) > float(opens[-1])

    # ── Scoring ───────────────────────────────────────────
    bull_score = 0.0
    bear_score = 0.0
    breakdown  = {}

    # 1) RSI
    if   rsi < 30:  bull_score += 3; breakdown["rsi"] = ("BULL", 3)
    elif rsi < 40:  bull_score += 2; breakdown["rsi"] = ("BULL", 2)
    elif rsi < 45:  bull_score += 1; breakdown["rsi"] = ("BULL", 1)
    elif rsi > 70:  bear_score += 3; breakdown["rsi"] = ("BEAR", 3)
    elif rsi > 60:  bear_score += 2; breakdown["rsi"] = ("BEAR", 2)
    elif rsi > 55:  bear_score += 1; breakdown["rsi"] = ("BEAR", 1)
    else:           breakdown["rsi"] = ("NEUTRAL", 0)

    # 2) MACD
    if   macd > macd_sig and macd_hist > 0:
        bull_score += 2; breakdown["macd"] = ("BULL", 2)
    elif macd < macd_sig and macd_hist < 0:
        bear_score += 2; breakdown["macd"] = ("BEAR", 2)
    else:
        breakdown["macd"] = ("NEUTRAL", 0)

    # 3) EMA alignment
    if   ema9 > ema21 > ema50:
        bull_score += 3; breakdown["ema"] = ("BULL", 3)
    elif ema9 < ema21 < ema50:
        bear_score += 3; breakdown["ema"] = ("BEAR", 3)
    else:
        breakdown["ema"] = ("NEUTRAL", 0)

    # 4) Bollinger position
    if   bb_pos < 0.20:
        bull_score += 2; breakdown["bb"] = ("BULL", 2)
    elif bb_pos > 0.80:
        bear_score += 2; breakdown["bb"] = ("BEAR", 2)
    else:
        breakdown["bb"] = ("NEUTRAL", 0)

    # 5) Volume spike
    if vol_ratio > 2:
        if is_green:
            bull_score += 1; breakdown["vol"] = ("BULL", 1)
        else:
            bear_score += 1; breakdown["vol"] = ("BEAR", 1)
    else:
        breakdown["vol"] = ("NEUTRAL", 0)

    # 5b) Volume anomaly — additional pressure scoring
    if vol_anom["anomaly"]:
        s = vol_anom["strength"]
        if vol_anom["type"] == "buying_pressure":
            pts = 3 if s == "extreme" else 2 if s == "high" else 1
            bull_score += pts; breakdown["vol_anom"] = (f"BUY_{s.upper()}", pts)
        else:
            pts = 3 if s == "extreme" else 2 if s == "high" else 1
            bear_score += pts; breakdown["vol_anom"] = (f"SELL_{s.upper()}", pts)
    else:
        breakdown["vol_anom"] = ("NORMAL", 0)

    # 6) Momentum
    if   momentum > 2:
        bull_score += 1; breakdown["mom"] = ("BULL", 1)
    elif momentum < -2:
        bear_score += 1; breakdown["mom"] = ("BEAR", 1)
    else:
        breakdown["mom"] = ("NEUTRAL", 0)

    # 7) ADX bonus / penalty
    if adx >= 25:
        # Trending — amplify winning side slightly
        if bull_score > bear_score:
            bull_score += 0.5
        elif bear_score > bull_score:
            bear_score += 0.5
        breakdown["adx"] = ("TRENDING", 0.5)
    elif adx < 20:
        # Ranging — dampen both sides
        bull_score = max(bull_score - 0.5, 0)
        bear_score = max(bear_score - 0.5, 0)
        breakdown["adx"] = ("RANGING", -0.5)
    else:
        breakdown["adx"] = ("WEAK_TREND", 0)

    # 8) Divergence bonus
    if divergence == "bullish":
        bull_score += 3; breakdown["div"] = ("BULL_DIV", 3)
    elif divergence == "bearish":
        bear_score += 3; breakdown["div"] = ("BEAR_DIV", 3)
    else:
        breakdown["div"] = ("NONE", 0)

    # 9) Open Interest scoring
    if   oi_signal == "bullish":
        bull_score += 2; breakdown["oi"] = ("BULL_OI", 2)
    elif oi_signal == "bearish":
        bear_score += 2; breakdown["oi"] = ("BEAR_OI", 2)
    elif oi_signal == "weak_bullish":
        bull_score += 1; breakdown["oi"] = ("WEAK_BULL_OI", 1)
    elif oi_signal == "weak_bearish":
        bear_score += 1; breakdown["oi"] = ("WEAK_BEAR_OI", 1)
    else:
        breakdown["oi"] = ("NEUTRAL", 0)

    # 10) Funding-rate adjustment — agresif (check after OI so final direction is stable)
    funding_warning = False
    funding_level   = "ok"

    if bull_score > bear_score:        # leaning LONG
        if funding_rate > 0.002:       # > +0.2%  strong warn
            bull_score = max(bull_score - 3, 0)
            funding_warning = True
            funding_level   = "strong_warn"
            breakdown["funding"] = ("STRONG_WARN_LONG", -3)
        elif funding_rate > 0.001:     # > +0.1%  warn
            bull_score = max(bull_score - 2, 0)
            funding_warning = True
            funding_level   = "warn"
            breakdown["funding"] = ("WARN_LONG", -2)
        elif funding_rate < -0.001:    # < -0.1%  kontra → bonus
            bull_score += 1
            breakdown["funding"] = ("CONTRA_LONG", 1)
        else:
            breakdown["funding"] = ("OK", 0)

    elif bear_score > bull_score:      # leaning SHORT
        if funding_rate < -0.002:      # < -0.2%  strong warn
            bear_score = max(bear_score - 3, 0)
            funding_warning = True
            funding_level   = "strong_warn"
            breakdown["funding"] = ("STRONG_WARN_SHORT", -3)
        elif funding_rate < -0.001:    # < -0.1%  warn
            bear_score = max(bear_score - 2, 0)
            funding_warning = True
            funding_level   = "warn"
            breakdown["funding"] = ("WARN_SHORT", -2)
        elif funding_rate > 0.001:     # > +0.1%  kontra → bonus
            bear_score += 1
            breakdown["funding"] = ("CONTRA_SHORT", 1)
        else:
            breakdown["funding"] = ("OK", 0)

    else:
        breakdown["funding"] = ("OK", 0)

    # ── Signal determination ──────────────────────────────
    diff = bull_score - bear_score

    if bull_score >= 3 and diff >= 1:
        signal_type = "LONG"
        confidence  = min(int(5 + abs(diff)), 10)
    elif bear_score >= 3 and diff <= -1:
        signal_type = "SHORT"
        confidence  = min(int(5 + abs(diff)), 10)
    elif diff >= 1:
        signal_type = "LEAN_LONG"
        confidence  = 6
    elif diff <= -1:
        signal_type = "LEAN_SHORT"
        confidence  = 6
    else:
        # Tiebreaker: RSI
        if rsi < 50:
            signal_type = "LEAN_LONG"
        elif rsi > 50:
            signal_type = "LEAN_SHORT"
        else:
            signal_type = "NEUTRAL"
        confidence = 5

    # ADX ranging penalty on confidence
    if adx < 20 and confidence > 6:
        confidence = max(confidence - 1, 5)

    # ── SL / TP via ATR ───────────────────────────────────
    price = float(closes[-1])
    a     = atr if atr > 0 else price * 0.005

    # R = distance entry → SL = 1.5 × ATR
    # TP1 = 1R, TP2 = 2R, TP3 = 3R
    if "LONG" in signal_type:
        sl   = price - 1.5 * a
        tp1  = price + 1.5 * a
        tp2  = price + 3.0 * a
        tp3  = price + 4.5 * a
    elif "SHORT" in signal_type:
        sl   = price + 1.5 * a
        tp1  = price - 1.5 * a
        tp2  = price - 3.0 * a
        tp3  = price - 4.5 * a
    else:
        sl = tp1 = tp2 = tp3 = price

    return SignalResult(
        symbol=symbol, timeframe=timeframe,
        signal_type=signal_type, confidence=confidence,
        bull_score=round(bull_score, 2), bear_score=round(bear_score, 2),
        entry_price=price, sl_price=sl, tp1_price=tp1, tp2_price=tp2, tp3_price=tp3,
        rsi=rsi, macd=macd, macd_signal=macd_sig, macd_hist=macd_hist, adx=adx,
        ema9=ema9, ema21=ema21, ema50=ema50,
        bb_upper=bb_up, bb_middle=bb_mid, bb_lower=bb_lo, bb_position=bb_pos,
        volume_ratio=vol_ratio, momentum=momentum,
        divergence=divergence,
        funding_rate=funding_rate, funding_warning=funding_warning,
        funding_level=funding_level, funding_trend=funding_trend,
        oi_change_1h=oi_change_1h, oi_trend=oi_trend, oi_signal=oi_signal,
        atr=a, volume_anomaly=vol_anom, score_breakdown=breakdown,
    )
