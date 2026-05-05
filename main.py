"""
main.py — Entry point
Jalankan: python main.py
"""
import asyncio
import logging
import sys
from config import LOG_LEVEL, LOG_FILE
from database import DatabaseManager
from scheduler import BotScheduler
from telegram_handler import TelegramBot


def setup_logging() -> None:
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    fmt   = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    # Suppress noisy libraries
    for lib in ("httpx", "httpcore", "telegram"):
        logging.getLogger(lib).setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== Trading Signal Bot starting ===")

    # 1) Database
    db = DatabaseManager()
    db.initialize()
    logger.info("Database initialised")

    # 2) Scheduler & Bot (cross-reference each other)
    scheduler     = BotScheduler(db)
    bot           = TelegramBot(db, scheduler)
    scheduler.bot = bot   # inject so scheduler can broadcast

    logger.info("Starting bot + scheduler…")

    # Run both loops concurrently
    await asyncio.gather(
        bot.start(),
        scheduler.start(),
        return_exceptions=True,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot dihentikan oleh user.")
    except Exception as exc:
        logging.getLogger(__name__).critical("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
