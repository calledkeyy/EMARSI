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

# ── Binance ───────────────────────────────────────────────
BINANCE_FUTURES_BASE = "https://fapi.binance.com"

# ── Valid timeframes (Binance format) ─────────────────────
VALID_TIMEFRAMES = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h", "1d",
]
