"""
fetcher.py — Async Binance Futures data fetcher
Klines, funding rate, mark price, symbol validation, Fear & Greed index
"""
from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional

import aiohttp
import numpy as np

from config import BINANCE_FUTURES_BASE

logger = logging.getLogger(__name__)


class BinanceFetcher:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ─────────────────────────────────────────────────────
    #  Klines  (OHLCV)
    # ─────────────────────────────────────────────────────
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
    ) -> Optional[Dict[str, np.ndarray]]:
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
        params  = {"symbol": symbol, "interval": interval, "limit": limit}

        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("Klines %s %s → HTTP %s", symbol, interval, resp.status)
                    return None
                data = await resp.json()

            if not data:
                return None

            return {
                "opens":   np.array([float(k[1]) for k in data]),
                "highs":   np.array([float(k[2]) for k in data]),
                "lows":    np.array([float(k[3]) for k in data]),
                "closes":  np.array([float(k[4]) for k in data]),
                "volumes": np.array([float(k[5]) for k in data]),
            }
        except Exception as e:
            logger.error("get_klines %s %s: %s", symbol, interval, e)
            return None

    # ─────────────────────────────────────────────────────
    #  Funding Rate
    # ─────────────────────────────────────────────────────
    async def get_funding_rate(self, symbol: str) -> float:
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/premiumIndex"
        try:
            async with session.get(url, params={"symbol": symbol}) as resp:
                if resp.status != 200:
                    return 0.0
                data = await resp.json()
                return float(data.get("lastFundingRate", 0))
        except Exception as e:
            logger.debug("get_funding_rate %s: %s", symbol, e)
            return 0.0

    # ─────────────────────────────────────────────────────
    #  Current Mark Price
    # ─────────────────────────────────────────────────────
    async def get_price(self, symbol: str) -> float:
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/price"
        try:
            async with session.get(url, params={"symbol": symbol}) as resp:
                if resp.status != 200:
                    return 0.0
                data = await resp.json()
                return float(data.get("price", 0))
        except Exception as e:
            logger.debug("get_price %s: %s", symbol, e)
            return 0.0

    # ─────────────────────────────────────────────────────
    #  Symbol Validation
    # ─────────────────────────────────────────────────────
    async def validate_symbol(self, symbol: str) -> bool:
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/exchangeInfo"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                trading = {
                    s["symbol"]
                    for s in data.get("symbols", [])
                    if s["status"] == "TRADING"
                }
                return symbol.upper() in trading
        except Exception as e:
            logger.error("validate_symbol %s: %s", symbol, e)
            return False

    # ─────────────────────────────────────────────────────
    #  Top USDT Futures by volume
    # ─────────────────────────────────────────────────────
    async def get_top_volume_symbols(self, limit: int = 30) -> List[str]:
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/24hr"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            usdt = [d for d in data if d["symbol"].endswith("USDT")]
            usdt.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
            return [p["symbol"] for p in usdt[:limit]]
        except Exception as e:
            logger.error("get_top_volume_symbols: %s", e)
            return []

    # ─────────────────────────────────────────────────────
    #  Dynamic Top 30  (excludes stablecoins)
    # ─────────────────────────────────────────────────────
    _STABLECOIN_PAIRS = frozenset({
        "BUSDUSDT", "USDCUSDT", "TUSDUSDT", "USDPUSDT", "FDUSDUSDT",
    })

    async def get_top30_by_volume(self) -> List[str]:
        """Top 30 USDT-M pairs by 24h quote volume, stablecoins excluded."""
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/24hr"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            usdt = [
                d for d in data
                if d["symbol"].endswith("USDT")
                and d["symbol"] not in self._STABLECOIN_PAIRS
            ]
            usdt.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
            return [p["symbol"] for p in usdt[:30]]
        except Exception as e:
            logger.error("get_top30_by_volume: %s", e)
            return []

    # ─────────────────────────────────────────────────────
    #  Fear & Greed Index  (alternative.me)
    # ─────────────────────────────────────────────────────
    async def get_fear_greed(self) -> Dict[str, str]:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get("https://api.alternative.me/fng/?limit=1") as resp:
                    if resp.status != 200:
                        return {"value": "N/A", "label": "Unknown"}
                    data = await resp.json()
                    item = data["data"][0]
                    return {
                        "value": item["value"],
                        "label": item["value_classification"],
                    }
        except Exception:
            return {"value": "N/A", "label": "Unknown"}

    # ─────────────────────────────────────────────────────
    #  Open Interest  (current + 1-hour history)
    # ─────────────────────────────────────────────────────
    async def get_open_interest(self, symbol: str) -> float:
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/openInterest"
        try:
            async with session.get(url, params={"symbol": symbol}) as resp:
                if resp.status != 200:
                    return 0.0
                data = await resp.json()
                return float(data.get("openInterest", 0))
        except Exception as e:
            logger.debug("get_open_interest %s: %s", symbol, e)
            return 0.0

    async def get_oi_history(
        self, symbol: str, period: str = "5m", limit: int = 12
    ) -> List[Dict]:
        """12 × 5m = 1 hour of OI data, oldest → newest."""
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/futures/data/openInterestHist"
        params  = {"symbol": symbol, "period": period, "limit": limit}
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [
                    {
                        "timestamp":       d["timestamp"],
                        "sumOpenInterest": float(d["sumOpenInterest"]),
                    }
                    for d in data
                ]
        except Exception as e:
            logger.debug("get_oi_history %s: %s", symbol, e)
            return []

    # ─────────────────────────────────────────────────────
    #  Funding Rate history  (trend analysis)
    # ─────────────────────────────────────────────────────
    async def get_funding_rate_history(
        self, symbol: str, limit: int = 8
    ) -> List[Dict]:
        """Last N funding records (oldest → newest) for trend detection."""
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/fundingRate"
        params  = {"symbol": symbol, "limit": limit}
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [
                    {
                        "fundingTime": d["fundingTime"],
                        "fundingRate": float(d["fundingRate"]),
                    }
                    for d in data
                ]
        except Exception as e:
            logger.debug("get_funding_rate_history %s: %s", symbol, e)
            return []

    # ─────────────────────────────────────────────────────
    #  All prices in one call  (for batch monitoring)
    # ─────────────────────────────────────────────────────
    async def get_all_prices(self) -> Dict[str, float]:
        session = await self._get_session()
        url     = f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/price"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return {d["symbol"]: float(d["price"]) for d in data}
        except Exception as e:
            logger.error("get_all_prices: %s", e)
            return {}
