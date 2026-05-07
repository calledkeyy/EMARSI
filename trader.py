"""
trader.py — Binance Futures Demo Auto-Trader
Fixed Dollar Risk (FDR) position sizing.

Demo Base  : https://demo-fapi.binance.com
API Key    : https://demo.binance.com/my/settings/api-management

CATATAN SL/TP:
  Sejak Desember 2025, STOP_MARKET & TAKE_PROFIT_MARKET via /fapi/v1/order
  deprecated (error -4120). Gunakan /fapi/v1/algoOrder sebagai primary,
  fallback ke STOP_MARKET/TAKE_PROFIT_MARKET untuk demo yang mungkin masih support.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import time
from typing import List, Optional
from urllib.parse import urlencode

import aiohttp

from config import (
    BINANCE_DEMO_BASE,
    BINANCE_DEMO_API_KEY,
    BINANCE_DEMO_API_SECRET,
    AUTO_TRADE_ENABLED,
    TRADE_LEVERAGE,
    BALANCE_SAFETY_PCT,
)

logger = logging.getLogger(__name__)


class BinanceTrader:

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self.base = BINANCE_DEMO_BASE

    # ── Session ──────────────────────────────────────────────
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"X-MBX-APIKEY": BINANCE_DEMO_API_KEY},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Signature ────────────────────────────────────────────
    def _sign(self, params: dict) -> str:
        return hmac.new(
            BINANCE_DEMO_API_SECRET.encode(),
            urlencode(params).encode(),
            hashlib.sha256,
        ).hexdigest()

    def _signed_params(self, params: dict) -> dict:
        params["timestamp"]  = int(time.time() * 1000)
        params["recvWindow"] = 5000
        params["signature"]  = self._sign(params)
        return params

    # ── Generic request ──────────────────────────────────────
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        signed: bool = True,
    ) -> Optional[dict | list]:
        session = await self._get_session()
        p = dict(params or {})
        if signed:
            p = self._signed_params(p)
        try:
            async with session.request(
                method, f"{self.base}{endpoint}", params=p
            ) as resp:
                data = await resp.json()
                if resp.status not in (200, 201):
                    logger.error(
                        "Demo API %s %s → %s: %s",
                        method, endpoint, resp.status, data,
                    )
                    return None
                return data
        except Exception as e:
            logger.error("Demo API %s %s: %s", method, endpoint, e)
            return None

    # ─────────────────────────────────────────────────────────
    #  Account
    # ─────────────────────────────────────────────────────────
    async def get_account(self) -> Optional[dict]:
        return await self._request("GET", "/fapi/v3/account")

    async def get_usdt_balance(self) -> float:
        """Baca availableBalance USDT real-time dari wallet Demo."""
        data = await self.get_account()
        if not data:
            return 0.0
        for asset in data.get("assets", []):
            if asset["asset"] == "USDT":
                return float(asset["availableBalance"])
        return 0.0

    async def get_wallet_balance(self) -> tuple[float, float]:
        """Return (total_balance, available_balance) dalam USDT."""
        data = await self.get_account()
        if not data:
            return 0.0, 0.0
        for asset in data.get("assets", []):
            if asset["asset"] == "USDT":
                return (
                    float(asset.get("walletBalance", 0)),
                    float(asset.get("availableBalance", 0)),
                )
        return 0.0, 0.0

    async def get_open_positions(self) -> List[dict]:
        """Posisi aktif di akun Demo (positionAmt != 0)."""
        data = await self._request("GET", "/fapi/v3/account")
        if not data:
            return []
        return [
            p for p in data.get("positions", [])
            if float(p.get("positionAmt", 0)) != 0
        ]

    # ─────────────────────────────────────────────────────────
    #  Symbol info & filters
    # ─────────────────────────────────────────────────────────
    async def get_symbol_info(self, symbol: str) -> Optional[dict]:
        data = await self._request(
            "GET", "/fapi/v1/exchangeInfo", params={}, signed=False
        )
        if not data:
            return None
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return None

    def _extract_filters(self, symbol_info: dict) -> dict:
        result = {
            "qty_precision":   3,
            "price_precision": 2,
            "min_qty":         0.001,
            "step_size":       0.001,
        }
        for f in symbol_info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
                result["step_size"] = step
                result["min_qty"]   = float(f["minQty"])
                s = f["stepSize"].rstrip("0")
                result["qty_precision"] = len(s.split(".")[-1]) if "." in s else 0
            elif f["filterType"] == "PRICE_FILTER":
                tick = f["tickSize"].rstrip("0")
                result["price_precision"] = len(tick.split(".")[-1]) if "." in tick else 0
        return result

    def _floor_qty(self, qty: float, step: float) -> float:
        """Floor qty ke kelipatan step_size — hindari reject order akibat presisi."""
        return math.floor(qty / step) * step

    # ─────────────────────────────────────────────────────────
    #  Leverage & margin type
    # ─────────────────────────────────────────────────────────
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        data = await self._request(
            "POST", "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": leverage},
        )
        if data:
            logger.info("Leverage %s → %dx", symbol, leverage)
            return True
        return False

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> None:
        """Error -4046 (sudah ISOLATED) diabaikan."""
        await self._request(
            "POST", "/fapi/v1/marginType",
            params={"symbol": symbol, "marginType": margin_type},
        )

    # ─────────────────────────────────────────────────────────
    #  Mark price
    # ─────────────────────────────────────────────────────────
    async def get_mark_price(self, symbol: str) -> float:
        data = await self._request(
            "GET", "/fapi/v1/premiumIndex",
            params={"symbol": symbol}, signed=False,
        )
        return float(data.get("markPrice", 0)) if data else 0.0

    # ─────────────────────────────────────────────────────────
    #  FDR Position Sizing
    # ─────────────────────────────────────────────────────────
    def calculate_qty_fdr(
        self,
        entry_price: float,
        sl_price: float,
        risk_usd: float,
        leverage: int,
        step_size: float,
        qty_precision: int,
        min_qty: float,
    ) -> tuple[float, float]:
        """
        Fixed Dollar Risk sizing.
          sl_pct   = |entry - sl| / entry
          margin   = risk_usd / (leverage × sl_pct)
          notional = margin × leverage
          qty      = floor(notional / entry, step_size)

        Returns (qty, margin_required).
        Raises ValueError jika tidak valid.
        """
        sl_pct = abs(entry_price - sl_price) / entry_price
        if sl_pct <= 0:
            raise ValueError("SL sama dengan entry price")

        margin   = risk_usd / (leverage * sl_pct)
        notional = margin * leverage
        qty_raw  = notional / entry_price
        qty      = self._floor_qty(qty_raw, step_size)
        qty      = round(qty, qty_precision)

        if qty < min_qty:
            raise ValueError(
                f"Qty hasil hitung ({qty:.6f}) di bawah minimum symbol ({min_qty:.6f}). "
                f"SL terlalu tipis atau risk_usd terlalu kecil."
            )
        return qty, margin

    # ─────────────────────────────────────────────────────────
    #  Open Position (Market + SL + TP3)
    # ─────────────────────────────────────────────────────────
    async def open_position(
        self,
        symbol: str,
        side: str,          # "LONG" atau "SHORT"
        sl_price: float,
        tp3_price: float,
        risk_usd: float,
        leverage: int = TRADE_LEVERAGE,
    ) -> Optional[dict]:
        """
        Buka posisi baru dengan FDR sizing.
        Returns:
          {"order_id", "qty", "entry_price", "margin_used", "sl_order_id", "tp_order_id"}
          {"skipped": True, "reason": ..., "margin_required": ..., "balance": ...}
          None jika API error.
        """
        if not AUTO_TRADE_ENABLED:
            return None
        if not BINANCE_DEMO_API_KEY or not BINANCE_DEMO_API_SECRET:
            logger.error("Demo API key/secret belum dikonfigurasi di .env")
            return None

        await self.set_margin_type(symbol, "ISOLATED")
        await self.set_leverage(symbol, leverage)

        sym_info = await self.get_symbol_info(symbol)
        if not sym_info:
            return None
        filters = self._extract_filters(sym_info)

        mark = await self.get_mark_price(symbol)
        if mark <= 0:
            return None

        try:
            qty, margin_required = self.calculate_qty_fdr(
                entry_price=mark,
                sl_price=sl_price,
                risk_usd=risk_usd,
                leverage=leverage,
                step_size=filters["step_size"],
                qty_precision=filters["qty_precision"],
                min_qty=filters["min_qty"],
            )
        except ValueError as e:
            logger.error("FDR sizing error %s: %s", symbol, e)
            return None

        available = await self.get_usdt_balance()
        if margin_required > available * BALANCE_SAFETY_PCT:
            logger.warning(
                "SKIP %s %s: margin dibutuhkan $%.2f > 90%% available $%.2f",
                side, symbol, margin_required, available,
            )
            return {
                "skipped":         True,
                "reason":          "insufficient_balance",
                "margin_required": round(margin_required, 2),
                "balance":         round(available, 2),
            }

        order_side = "BUY" if side == "LONG" else "SELL"
        order = await self._request("POST", "/fapi/v1/order", params={
            "symbol":   symbol,
            "side":     order_side,
            "type":     "MARKET",
            "quantity": qty,
        })
        if not order:
            return None

        logger.info(
            "OPEN %s %s qty=%.5f @~$%.2f | margin=$%.2f | risk=$%.2f | lev=%dx",
            side, symbol, qty, mark, margin_required, risk_usd, leverage,
        )

        await asyncio.sleep(0.5)
        sl_id = await self._place_sl_algo(symbol, side, qty, sl_price, filters)
        tp_id = await self._place_tp_algo(symbol, side, qty, tp3_price, filters)

        return {
            "order_id":    order.get("orderId"),
            "qty":         qty,
            "entry_price": mark,
            "margin_used": round(margin_required, 2),
            "sl_order_id": sl_id,
            "tp_order_id": tp_id,
        }

    # ─────────────────────────────────────────────────────────
    #  Average Position
    # ─────────────────────────────────────────────────────────
    async def add_to_position(
        self,
        symbol: str,
        side: str,
        current_qty: float,
        current_entry: float,
        sl_price: float,        # SL lama — DIPERTAHANKAN
        new_tp3_price: float,   # TP3 dari sinyal baru
        old_tp_order_id: int | None,
        risk_usd: float,
        leverage: int = TRADE_LEVERAGE,
    ) -> Optional[dict]:
        """
        Tambah ke posisi existing (averaging).
        - Qty add-on dihitung dari (entry_baru → sl_lama)
        - Entry average dihitung ulang
        - TP3 lama di-cancel, TP3 baru dipasang untuk qty total
        - SL lama TIDAK diubah
        """
        if not AUTO_TRADE_ENABLED:
            return None

        sym_info = await self.get_symbol_info(symbol)
        if not sym_info:
            return None
        filters = self._extract_filters(sym_info)

        mark = await self.get_mark_price(symbol)
        if mark <= 0:
            return None

        try:
            qty_add, margin_required = self.calculate_qty_fdr(
                entry_price=mark,
                sl_price=sl_price,
                risk_usd=risk_usd,
                leverage=leverage,
                step_size=filters["step_size"],
                qty_precision=filters["qty_precision"],
                min_qty=filters["min_qty"],
            )
        except ValueError as e:
            logger.error("FDR averaging error %s: %s", symbol, e)
            return None

        available = await self.get_usdt_balance()
        if margin_required > available * BALANCE_SAFETY_PCT:
            logger.warning(
                "SKIP avg %s: margin $%.2f > 90%% balance $%.2f",
                symbol, margin_required, available,
            )
            return {
                "skipped":         True,
                "reason":          "insufficient_balance",
                "margin_required": round(margin_required, 2),
                "balance":         round(available, 2),
            }

        order_side = "BUY" if side == "LONG" else "SELL"
        order = await self._request("POST", "/fapi/v1/order", params={
            "symbol":   symbol,
            "side":     order_side,
            "type":     "MARKET",
            "quantity": qty_add,
        })
        if not order:
            return None

        new_total_qty = self._floor_qty(current_qty + qty_add, filters["step_size"])
        new_total_qty = round(new_total_qty, filters["qty_precision"])
        avg_entry = (current_qty * current_entry + qty_add * mark) / (current_qty + qty_add)

        logger.info(
            "AVG %s %s: +%.5f @$%.2f → total=%.5f avg_entry=$%.2f",
            side, symbol, qty_add, mark, new_total_qty, avg_entry,
        )

        new_tp_id = None
        if old_tp_order_id:
            await self.cancel_algo_order(symbol, old_tp_order_id)
        await asyncio.sleep(0.3)
        new_tp_id = await self._place_tp_algo(symbol, side, new_total_qty, new_tp3_price, filters)

        return {
            "qty_added":       qty_add,
            "new_qty":         new_total_qty,
            "avg_entry":       avg_entry,
            "new_tp_order_id": new_tp_id,
            "margin_used":     round(margin_required, 2),
        }

    # ─────────────────────────────────────────────────────────
    #  Close Position
    # ─────────────────────────────────────────────────────────
    async def close_position(
        self,
        symbol: str,
        side: str,
        qty: float | None = None,
        sl_order_id: int | None = None,
        tp_order_id: int | None = None,
    ) -> Optional[dict]:
        """Tutup posisi dengan market order reduceOnly. Cancel SL & TP jika ada."""
        if not AUTO_TRADE_ENABLED:
            return None

        if qty is None or qty <= 0:
            positions = await self.get_open_positions()
            for pos in positions:
                if pos["symbol"] == symbol:
                    qty = abs(float(pos["positionAmt"]))
                    break
            if not qty or qty <= 0:
                logger.warning("Tidak ada posisi terbuka untuk %s", symbol)
                return None

        close_side = "SELL" if side == "LONG" else "BUY"
        result = await self._request("POST", "/fapi/v1/order", params={
            "symbol":     symbol,
            "side":       close_side,
            "type":       "MARKET",
            "quantity":   qty,
            "reduceOnly": "true",
        })
        if result:
            logger.info("CLOSE %s %s qty=%.5f", side, symbol, qty)
            if sl_order_id:
                await self.cancel_algo_order(symbol, sl_order_id)
            if tp_order_id:
                await self.cancel_algo_order(symbol, tp_order_id)
        return result

    # ─────────────────────────────────────────────────────────
    #  Algo Orders (SL / TP)
    # ─────────────────────────────────────────────────────────
    async def _place_sl_algo(
        self,
        symbol: str,
        side: str,
        qty: float,
        sl_price: float,
        filters: dict,
    ) -> Optional[int]:
        sl_side    = "SELL" if side == "LONG" else "BUY"
        sl_rounded = round(sl_price, filters["price_precision"])

        # Primary: Algo Service
        data = await self._request("POST", "/fapi/v1/algoOrder", params={
            "symbol":      symbol,
            "side":        sl_side,
            "type":        "VP",
            "quantity":    qty,
            "stopPrice":   sl_rounded,
            "reduceOnly":  "true",
            "workingType": "MARK_PRICE",
        })
        # Fallback: STOP_MARKET (demo mungkin masih support)
        if not data:
            data = await self._request("POST", "/fapi/v1/order", params={
                "symbol":      symbol,
                "side":        sl_side,
                "type":        "STOP_MARKET",
                "stopPrice":   sl_rounded,
                "quantity":    qty,
                "reduceOnly":  "true",
                "workingType": "MARK_PRICE",
            })
        if data:
            oid = data.get("algoId") or data.get("orderId")
            logger.info("SL order %s @ $%.4f (id=%s)", symbol, sl_rounded, oid)
            return oid
        logger.error("Gagal pasang SL untuk %s", symbol)
        return None

    async def _place_tp_algo(
        self,
        symbol: str,
        side: str,
        qty: float,
        tp_price: float,
        filters: dict,
    ) -> Optional[int]:
        tp_side    = "SELL" if side == "LONG" else "BUY"
        tp_rounded = round(tp_price, filters["price_precision"])

        # Primary: Algo Service
        data = await self._request("POST", "/fapi/v1/algoOrder", params={
            "symbol":      symbol,
            "side":        tp_side,
            "type":        "VP",
            "quantity":    qty,
            "stopPrice":   tp_rounded,
            "reduceOnly":  "true",
            "workingType": "MARK_PRICE",
        })
        # Fallback: TAKE_PROFIT_MARKET
        if not data:
            data = await self._request("POST", "/fapi/v1/order", params={
                "symbol":      symbol,
                "side":        tp_side,
                "type":        "TAKE_PROFIT_MARKET",
                "stopPrice":   tp_rounded,
                "quantity":    qty,
                "reduceOnly":  "true",
                "workingType": "MARK_PRICE",
            })
        if data:
            oid = data.get("algoId") or data.get("orderId")
            logger.info("TP3 order %s @ $%.4f (id=%s)", symbol, tp_rounded, oid)
            return oid
        logger.error("Gagal pasang TP3 untuk %s", symbol)
        return None

    async def cancel_algo_order(self, symbol: str, order_id: int) -> bool:
        data = await self._request(
            "DELETE", "/fapi/v1/algoOrder",
            params={"symbol": symbol, "algoId": order_id},
        )
        if data:
            return True
        data = await self._request(
            "DELETE", "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
        )
        return bool(data)

    async def cancel_all_orders(self, symbol: str) -> None:
        await self._request(
            "DELETE", "/fapi/v1/algoOpenOrders", params={"symbol": symbol}
        )
        await self._request(
            "DELETE", "/fapi/v1/allOpenOrders", params={"symbol": symbol}
        )
        logger.info("Semua order %s dibatalkan", symbol)

    async def get_open_orders(self, symbol: str | None = None) -> List[dict]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/fapi/v1/openOrders", params=params)
        return data if isinstance(data, list) else []
