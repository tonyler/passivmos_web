#!/usr/bin/env python3
"""
PassivMOS Logging — centralised setup with rotation + emoji formatter.
Import and call setup_logging() once at startup, then use getLogger() normally.
"""
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE        = Path(__file__).parent.parent / "data" / "backend.log"
LOG_MAX_BYTES   = 5 * 1024 * 1024   # 5 MB per file
LOG_BACKUP_COUNT = 5                 # keep 5 rotated files (25 MB total)

_LEVEL_EMOJI = {
    "DEBUG":    "🔍",
    "INFO":     "  ",   # blank — info is the default, no noise
    "WARNING":  "⚠️ ",
    "ERROR":    "❌",
    "CRITICAL": "🚨",
}

# Event emojis used throughout the codebase
EMOJI = {
    # lifecycle
    "start":     "🚀",
    "stop":      "🛑",
    "ready":     "✅",
    "error":     "❌",
    "warn":      "⚠️",
    # prices
    "price":     "💰",
    "coingecko": "🦎",
    "ratelimit": "🚦",
    # portfolio / scanning
    "scan":      "🔭",
    "user":      "👤",
    "portfolio": "📊",
    "holding":   "💎",
    # backend HTTP
    "get":       "📥",
    "post":      "📤",
    "delete":    "🗑️",
    "ok":        "✅",
    "fail":      "❌",
    # frontend / UI events
    "signin":    "🔑",
    "signout":   "🚪",
    "wallet_add": "➕",
    "wallet_rm": "🗑️",
    "ui_scan":   "🔍",
    "ui_done":   "🏁",
    "period":    "📅",
    "load":      "📂",
    # system
    "recycle":   "♻️",
    "file":      "📁",
    "clock":     "⏱️",
}


class _EmojiFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.level_emoji = _LEVEL_EMOJI.get(record.levelname, "  ")
        return super().format(record)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Call once at startup. Configures:
      - RotatingFileHandler → data/backend.log  (5 MB × 5 = 25 MB max)
      - StreamHandler       → stdout            (for systemd journal)
    Returns the root 'passivmos' logger.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    fmt      = "%(asctime)s %(level_emoji)s %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = _EmojiFormatter(fmt=fmt, datefmt=date_fmt)

    # ── file handler with rotation ────────────────────────────────────────────
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # ── stdout handler ────────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    # ── root logger ───────────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # clear any handlers already added (e.g. basicConfig called elsewhere)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # suppress noisy third-party libs
    for noisy in ("uvicorn.access", "aiohttp", "aiohttp.access",
                  "urllib3", "asyncio", "slowapi"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    log = logging.getLogger("passivmos")
    log.info(f"{EMOJI['recycle']} Log rotation: {LOG_MAX_BYTES//1024//1024} MB × {LOG_BACKUP_COUNT} files → {LOG_FILE}")
    return log
