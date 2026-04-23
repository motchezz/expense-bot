"""
main.py — Single-user Expense & Sales Tracker Bot
---------------------------------------------------
Just runs the Telegram bot. No web server, no database.
All config comes from environment variables.

Required env vars:
  TELEGRAM_BOT_TOKEN   — from @BotFather
  SPREADSHEET_ID       — Google Sheet ID (from its URL)
  GOOGLE_CREDENTIALS_JSON — base64-encoded service account JSON

Start locally:  python main.py
Railway Procfile: worker: python main.py
"""

import asyncio
import logging

from bot import run_bot

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

if __name__ == "__main__":
    asyncio.run(run_bot())
