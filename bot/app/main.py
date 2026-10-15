"""Entrypoint: `python -m app.main` runs the bot; `python -m app.main export` writes stats.json once."""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import admin, handlers
from .analytics import export_stats
from .config import config
from .db import DB
from .llm import GigaChat
from .providers import get_provider

log = logging.getLogger("imgrsz")


async def stats_loop(db: DB, every: int = 300):
    while True:
        try:
            export_stats(db)
        except Exception:
            log.exception("stats export failed")
        await asyncio.sleep(every)


async def run_bot():
    db = DB(config.db_path)
    props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot = Bot(config.bot_token, default=props)
    admin_bot = Bot(config.admin_bot_token, default=props) if config.admin_bot_token else None
    handlers.setup(db, GigaChat(), get_provider(), admin_bot)
    dp = Dispatcher()
    dp.include_router(handlers.router)
    asyncio.create_task(stats_loop(db))
    log.info("bot started: provider=%s model=%s admin_bot=%s", config.image_provider, config.gigachat_model, bool(admin_bot))
    polls = [dp.start_polling(bot)]
    if admin_bot:
        admin.setup(db)
        admin_dp = Dispatcher()
        admin_dp.include_router(admin.router)
        polls.append(admin_dp.start_polling(admin_bot, handle_signals=False))
    await asyncio.gather(*polls)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.argv[1:] == ["export"]:
        print(export_stats(DB(config.db_path)))
        return
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
