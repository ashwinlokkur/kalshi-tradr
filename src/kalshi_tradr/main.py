from __future__ import annotations

import asyncio
import logging
import signal

from dotenv import load_dotenv

from .config import load_settings
from .db import Database
from .kalshi.client import KalshiAsyncClient
from .telegram_bot.bot import build_application

log = logging.getLogger("kalshi_tradr")


async def _run() -> None:
    load_dotenv()
    settings = load_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log.info("connecting to Postgres…")
    db = await Database.connect(settings.database_url)

    log.info("initializing Kalshi client (%s)…", settings.kalshi_env)
    kalshi = KalshiAsyncClient(
        base_url=settings.kalshi_base_url,
        api_key_id=settings.kalshi_api_key_id,
        private_key_pem=settings.read_private_key(),
    )

    log.info("building Telegram application…")
    app = build_application(settings=settings, db=db, kalshi=kalshi)

    stop = asyncio.Event()

    def _on_signal(*_: object) -> None:
        log.info("shutdown requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    try:
        await app.initialize()
        await app.start()
        assert app.updater is not None
        await app.updater.start_polling()
        log.info("bot is running; waiting for updates")
        await stop.wait()
    finally:
        log.info("stopping…")
        if app.updater is not None:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await kalshi.aclose()
        await db.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
