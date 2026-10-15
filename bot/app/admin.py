"""Admin bot: delivers a copy of every result (original + output) to admins only.

Bots cannot message a user first, so each admin from config.admin_usernames
must send /start to the admin bot once; their chat_id is then stored in `admins`.
"""
import html
import logging

from aiogram import Bot, Router
from aiogram.types import BufferedInputFile, InputMediaDocument, Message

from .config import config
from .db import DB

log = logging.getLogger(__name__)
router = Router()


def setup(db: DB):
    router.db = db


@router.message()
async def any_message(msg: Message):
    username = (msg.from_user.username or "").lower()
    if username not in config.admin_usernames:
        await msg.answer("Нет доступа.")
        return
    router.db.add_admin(msg.chat.id, username)
    await msg.answer("✅ Вы администратор. Сюда будут приходить все результаты обработки.")


async def notify(admin_bot: Bot | None, db: DB, *, job_id: int, user, request: str, brief: str,
                 price: int, cost_usd: float, seconds: float, original: bytes, src_ext: str, result) -> None:
    """Send original + result to every registered admin. Never raises."""
    if not admin_bot:
        return
    who = f"@{user.username}" if user.username else user.full_name
    caption = (
        f"#job{job_id} · {html.escape(who)} (<code>{user.id}</code>)\n"
        f"<b>Запрос:</b> {html.escape(request[:300])}\n"
        f"<b>Бриф:</b> {html.escape(brief[:300])}\n"
        f"<b>Итог:</b> {result.width}×{result.height}, {result.ext.upper()}, {result.kb} КБ\n"
        f"Цена {price} р. · себестоимость ${cost_usd:.3f} · {seconds:.1f} с"
    )[:1024]
    media = [
        InputMediaDocument(media=BufferedInputFile(original, filename=f"job{job_id}_before.{src_ext}")),
        InputMediaDocument(media=BufferedInputFile(result.data, filename=f"job{job_id}_after.{result.ext}"),
                           caption=caption, parse_mode="HTML"),
    ]
    for chat_id in db.admin_chats():
        try:
            await admin_bot.send_media_group(chat_id, media)
        except Exception:
            log.exception("admin notify failed for chat %s", chat_id)
