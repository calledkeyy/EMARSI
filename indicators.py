"""
indicators.py — All technical indicator calculations
RSI, MACD, Bollinger Bands, EMA, Volume Ratio,
Momentum, ADX, ATR, Divergence detection,
Open Interest analysis, Funding Rate trend
"""
from __future__ import annotations
import numpy as np
from typing import Tuple, Dict, List


# ─────────────────────────────────────────────────────────────
#  RSI  (SMA-seeded, then Wilder-smoothed — sesuai spec)
# ─────────────────────────────────────────────────────────────
def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
    src = closes[-100:] if len(closes) >= 100 else closes
    if len(src) < period + 1:
        return 50.0

    deltas = np.diff(src.astype(float))
    gains  = np.where(deltas > 0,  deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ─────────────────────────────────────────────────────────────
#  EMA
# ─────────────────────────────────────────────────────────────
def calculate_ema(data: np.ndarray, period: int) -> np.ndarray:
    data = data.astype(float)
    if len(data) < period:
        return np.full(len(data), data[-1])

    ema = np.zeros(len(data))
    ema[period - 1] = np.mean(data[:period])
    k = 2 / (period + 1)
    for i in range(period, len(data)):
        ema[i] = data[i] * k + ema[i - 1] * (1 - k)
    return ema


def calculate_emas(closes: np.ndarray) -> Tuple[float, float, float]:
    """Returns (ema9, ema21, ema50)"""
    return (
        calculate_ema(closes, 9)[-1],
        calculate_ema(closes, 21)[-1],
        calculate_ema(closes, 50)[-1],
    )


# ─────────────────────────────────────────────────────────────
#  MACD  (EMA12 - EMA26, signal=EMA9, histogram)
# ─────────────────────────────────────────────────────────────
def calculate_macd(closes: np.ndarray) -> Tuple[float, float, float]:
    """Returns (macd_line, signal_line, histogram)"""
    if len(closes) < 35:
        return 0.0, 0.0, 0.0

    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    macd_series = ema12 - ema26

    valid = macd_series[25:]          # EMA26 meaningful from index 25
    if len(valid) < 9:
        return 0.0, 0.0, 0.0

    sig_series = calculate_ema(valid, 9)
    macd_val   = macd_series[-1]
    sig_val    = sig_series[-1]
    histogram  = macd_val - sig_val
    return round(macd_val, 8), round(sig_val, 8), round(histogram, 8)


# ─────────────────────────────────────────────────────────────
#  Bollinger Bands  (SMA20 ± 2σ)
# ─────────────────────────────────────────────────────────────
def calculate_bollinger(
    closes: np.ndarray, period: int = 20
) -> Tuple[float, float, float, float]:
    """Returns (upper, middle, lower, position 0-1)"""
    if len(closes) < period:
        return 0.0, float(closes[-1]), 0.0, 0.5

    src    = closes[-period:].astype(float)
    middle = float(np.mean(src))
    std    = float(np.std(src, ddof=0))
    upper  = middle + 2 * std
    lower  = middle - 2 * std

    band_width = upper - lower
    position   = (float(closes[-1]) - lower) / band_width if band_width > 0 else 0.5
    position   = max(0.0, min(1.0, position))

    return round(upper, 6), round(middle, 6), round(lower, 6), round(position, 4)


# ─────────────────────────────────────────────────────────────
#  Volume Ratio
# ─────────────────────────────────────────────────────────────
def calculate_volume_ratio(volumes: np.ndarray, period: int = 20) -> float:
    if len(volumes) < period + 1:
        return 1.0
    avg = float(np.mean(volumes[-period - 1 : -1]))
    if avg == 0:
        return 1.0
    return round(float(volumes[-1]) / avg, 3)


# ─────────────────────────────────────────────────────────────
#  Momentum  (% change over N candles)
# ─────────────────────────────────────────────────────────────
def calculate_momentum(closes: np.ndarray, period: int = 5) -> float:
    if len(closes) < period + 1:
        return 0.0
    base = float(closes[-(period + 1)])
    if base == 0:
        return 0.0
    return round(((float(closes[-1]) - base) / base) * 100, 4)


# ─────────────────────────────────────────────────────────────
#  ATR  (Average True Range)
# ─────────────────────────────────────────────────────────────
def calculate_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    if len(closes) < period + 1:
        return float(closes[-1]) * 0.005

    tr_arr = np.array([
        max(
            float(highs[i]) - float(lows[i]),
            abs(float(highs[i]) - float(closes[i - 1])),
            abs(float(lows[i])  - float(closes[i - 1])),
        )
        for i in range(1, len(closes))
    ])
    return round(float(np.mean(tr_arr[-period:])), 8)


# ─────────────────────────────────────────────────────────────
#  ADX  (Average Directional Index)
# ─────────────────────────────────────────────────────────────
def calculate_adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    if len(closes) < period * 2 + 1:
        return 0.0

    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        h, l, pc = float(highs[i]), float(lows[i]), float(closes[i - 1])
        ph, pl   = float(highs[i - 1]), float(lows[i - 1])
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, down = h - ph, pl - l
        plus_dm.append(up   if up > down and up > 0   else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    tr_a  = np.array(tr_list,  dtype=float)
    pdm_a = np.array(plus_dm,  dtype=float)
    ndm_a = np.array(minus_dm, dtype=float)

    # Wilder smoothing
    def wilder_smooth(arr: np.ndarray) -> np.ndarray:
        s = np.zeros(len(arr))
        s[period - 1] = np.sum(arr[:period])
        for i in range(period, len(arr)):
            s[i] = s[i - 1] - (s[i - 1] / period) + arr[i]
        return s

    atr_s  = wilder_smooth(tr_a)
    pdi_s  = wilder_smooth(pdm_a)
    ndi_s  = wilder_smooth(ndm_a)

    safe_atr = np.where(atr_s == 0, 1, atr_s)
    pdi_pct  = 100 * pdi_s / safe_atr
    ndi_pct  = 100 * ndi_s / safe_atr

    di_sum  = pdi_pct + ndi_pct
    di_diff = np.abs(pdi_pct - ndi_pct)
    dx      = 100 * di_diff / np.where(di_sum == 0, 1, di_sum)

    # ADX = Wilder smoothed DX
    if len(dx) < 2 * period:
        return 0.0
    adx_val = float(np.mean(dx[period - 1 : 2 * period - 1]))
    for i in range(2 * period - 1, len(dx)):
        adx_val = (adx_val * (period - 1) + dx[i]) / period

    return round(adx_val, 2)


# ─────────────────────────────────────────────────────────────
#  RSI Divergence Detection
# ─────────────────────────────────────────────────────────────
def detect_divergence(
    closes: np.ndarray,
    rsi_history: list[float],
    lookback: int = 20,
) -> str:
    """
    Returns 'bullish', 'bearish', or 'none'.
    Bullish  = price lower-low  but RSI higher-low  (reversal up)
    Bearish  = price higher-high but RSI lower-high (reversal down)
    """
    if len(closes) < lookback or len(rsi_history) < lookback:
        return "none"

    prices = np.array(closes[-lookback:], dtype=float)
    rsis   = np.array(rsi_history[-lookback:], dtype=float)

    mid = lookback // 2

    # Bullish divergence
    prev_low_idx = int(np.argmin(prices[:mid]))
    curr_low_idx = mid + int(np.argmin(prices[mid:]))
    if prices[curr_low_idx] < prices[prev_low_idx]:
        if rsis[curr_low_idx] > rsis[prev_low_idx]:
            return "bullish"

    # Bearish divergence
    prev_hi_idx = int(np.argmax(prices[:mid]))
    curr_hi_idx = mid + int(np.argmax(prices[mid:]))
    if prices[curr_hi_idx] > prices[prev_hi_idx]:
        if rsis[curr_hi_idx] < rsis[prev_hi_idx]:
            return "bearish"

    return "none"


# ─────────────────────────────────────────────────────────────
#  Open Interest Analysis
# ─────────────────────────────────────────────────────────────
def calculate_oi_change(
    oi_history: List[Dict],
    price_change_pct: float = 0.0,
) -> Dict:
    """
    Analyse 1-hour OI history.
    price_change_pct: % change in price over the same window (pass momentum).

    Returns:
        oi_current    — latest OI value
        oi_change_1h  — % change from oldest to newest bucket
        oi_trend      — "rising" | "falling" | "flat"
        signal        — "bullish" | "bearish" | "weak_bullish" | "weak_bearish" | "neutral"

    Signal logic (threshold: |oi_change_1h| > 2%):
        OI ↑ + price ↑ → bullish  (new longs entering)
        OI ↑ + price ↓ → bearish  (new shorts entering)
        OI ↓ + price ↑ → weak_bullish  (short covering)
        OI ↓ + price ↓ → weak_bearish  (long liquidation)
    """
    if not oi_history or len(oi_history) < 2:
        return {
            "oi_current":   0.0,
            "oi_change_1h": 0.0,
            "oi_trend":     "flat",
            "signal":       "neutral",
        }

    vals       = [h["sumOpenInterest"] for h in oi_history]
    oi_current = vals[-1]
    oi_old     = vals[0]

    oi_change_1h = ((oi_current - oi_old) / oi_old * 100) if oi_old > 0 else 0.0

    if abs(oi_change_1h) < 0.5:
        oi_trend = "flat"
    elif oi_change_1h > 0:
        oi_trend = "rising"
    else:
        oi_trend = "falling"

    signal = "neutral"
    if abs(oi_change_1h) >= 2.0:
        oi_up   = oi_trend == "rising"
        oi_down = oi_trend == "falling"
        px_up   = price_change_pct > 0
        px_down = price_change_pct < 0

        if   oi_up   and px_up:   signal = "bullish"
        elif oi_up   and px_down: signal = "bearish"
        elif oi_down and px_up:   signal = "weak_bullish"
        elif oi_down and px_down: signal = "weak_bearish"

    return {
        "oi_current":   round(oi_current, 2),
        "oi_change_1h": round(oi_change_1h, 3),
        "oi_trend":     oi_trend,
        "signal":       signal,
    }


# ─────────────────────────────────────────────────────────────
#  Funding Rate Trend
# ─────────────────────────────────────────────────────────────
def calculate_funding_trend(funding_history: List[Dict]) -> str:
    """
    Determine funding rate trend from historical records (oldest → newest).
    Returns "rising" | "falling" | "stable".
    """
    if len(funding_history) < 2:
        return "stable"
    rates = [h["fundingRate"] for h in funding_history]
    delta = rates[-1] - rates[0]
    if delta > 0.0001:
        return "rising"
    if delta < -0.0001:
        return "falling"
    return "stable"


# ─────────────────────────────────────────────────────────────
#  Volume Anomaly Detector
# ─────────────────────────────────────────────────────────────
def detect_volume_anomaly(
    volumes: np.ndarray,
    closes: np.ndarray,
    opens: np.ndarray,
    period: int = 20,
) -> Dict:
    """
    Detect abnormal volume spikes and classify buying/selling pressure.

    Returns:
        anomaly      — True if ratio > 2×
        type         — "buying_pressure" | "selling_pressure" | "normal"
        strength     — "extreme" (>5×) | "high" (>3×) | "moderate" (>2×) | "normal"
        ratio        — current vol / avg vol
        consecutive  — candles in a row (from latest) with vol > 1.5× avg
        cvd_trend    — "bullish" | "bearish"  (last-10-candle Cumulative Volume Delta)
    """
    _default = {
        "anomaly": False, "type": "normal", "strength": "normal",
        "ratio": 1.0, "consecutive": 0, "cvd_trend": "bullish",
    }
    if len(volumes) < period + 1:
        return _default

    avg_vol = float(np.mean(volumes[-(period + 1):-1]))
    if avg_vol == 0:
        return _default

    current_vol = float(volumes[-1])
    ratio = round(current_vol / avg_vol, 3)

    # Strength & anomaly flag
    if ratio > 5:
        strength, anomaly = "extreme", True
    elif ratio > 3:
        strength, anomaly = "high", True
    elif ratio > 2:
        strength, anomaly = "moderate", True
    else:
        strength, anomaly = "normal", False

    # Type — direction of the anomaly candle
    is_green = float(closes[-1]) > float(opens[-1])
    vol_type = ("buying_pressure" if is_green else "selling_pressure") if anomaly else "normal"

    # CVD — last 10 candles
    n = min(10, len(volumes))
    buy_vol = sell_vol = 0.0
    for i in range(-n, 0):
        v = float(volumes[i])
        if float(closes[i]) > float(opens[i]):
            buy_vol  += v
        else:
            sell_vol += v
    cvd_trend = "bullish" if buy_vol >= sell_vol else "bearish"

    # Consecutive candles with vol > 1.5× avg (from latest, going back)
    consecutive = 0
    for i in range(-1, -len(volumes), -1):
        if float(volumes[i]) > 1.5 * avg_vol:
            consecutive += 1
        else:
            break

    return {
        "anomaly":     anomaly,
        "type":        vol_type,
        "strength":    strength,
        "ratio":       ratio,
        "consecutive": consecutive,
        "cvd_trend":   cvd_trend,
    }
