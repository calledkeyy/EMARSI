"""
indicators.py — All technical indicator calculations
RSI, MACD, Bollinger Bands, EMA, Volume Ratio,
Momentum, ADX, ATR, Divergence detection
"""
from __future__ import annotations
import numpy as np
from typing import Tuple


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
