"""
config.py — Bot configuration from environment variables
Copy .env.example to .env and fill in your values
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

_raw_ids = os.getenv("ALLOWED_CHAT_IDS", "")
ALLOWED_CHAT_IDS: list[int] = (
    [int(x.strip()) for x in _raw_ids.split(",") if x.strip()]
    if _raw_ids else []
)

# ── Logging ───────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.getenv("LOG_FILE", "bot.log")

# ── Binance Public API ────────────────────────────────────
BINANCE_FUTURES_BASE = "https://fapi.binance.com"

# ── Binance Demo Trading API ──────────────────────────────
# Buat API key di: https://demo.binance.com/my/settings/api-management
BINANCE_DEMO_BASE       = "https://demo-fapi.binance.com"
BINANCE_DEMO_API_KEY    = os.getenv("BINANCE_DEMO_API_KEY", "")
BINANCE_DEMO_API_SECRET = os.getenv("BINANCE_DEMO_API_SECRET", "")

# ── Auto-trade settings ───────────────────────────────────
AUTO_TRADE_ENABLED   = os.getenv("AUTO_TRADE_ENABLED", "true").lower() == "true"
TRADE_RISK_USD       = float(os.getenv("TRADE_RISK_USD", "5.0"))
TRADE_LEVERAGE       = int(os.getenv("TRADE_LEVERAGE", "20"))
TRADE_MIN_CONFIDENCE = int(os.getenv("TRADE_MIN_CONFIDENCE", "7"))
BALANCE_SAFETY_PCT   = float(os.getenv("BALANCE_SAFETY_PCT", "0.9"))

# ── Valid timeframes (Binance format) ─────────────────────
VALID_TIMEFRAMES = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h", "1d",
]
