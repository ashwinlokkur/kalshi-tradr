from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from ..config import Settings
from ..db import Database
from ..kalshi.client import KalshiAsyncClient
from . import handlers

log = logging.getLogger(__name__)


def build_application(*, settings: Settings, db: Database, kalshi: KalshiAsyncClient) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["deps"] = handlers.Deps(settings=settings, db=db, kalshi=kalshi)

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    app.add_handler(CommandHandler("scan", handlers.cmd_scan))
    app.add_handler(CommandHandler("bet", handlers.cmd_bet))
    app.add_handler(CallbackQueryHandler(handlers.on_callback))

    return app
