"""Admin bot: delivers a copy of every result (original + output) to admins only.

Bots cannot message a user first, so each admin from config.admin_usernames
must send /start to the admin bot once; their chat_id is then stored in `admins`.
"""
import html
import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, InputMediaDocument, Message

from .config import config
from .db import DB

log = logging.getLogger(__name__)
router = Router()


def setup(db: DB):
    router.db = db


def _is_admin(msg: Message) -> bool:
    return (msg.from_user.username or "").lower() in config.admin_usernames


@router.message(Command("drop"))
async def drop(msg: Message, command: CommandObject):
    """/drop @username — the user becomes new again (welcome text + bonus) for testing. /drop alone drops yourself."""
    if not _is_admin(msg):
        await msg.answer("Нет доступа.")
        return
    who = (command.args or msg.from_user.username or str(msg.from_user.id)).split()[0]
    tg_id = router.db.drop_user(who)
    if tg_id is None:
        await msg.answer(f"Пользователь {html.escape(who)} не найден.")
        return
    router.db.event(msg.from_user.id, "admin_drop_user", dropped=tg_id)
    await msg.answer(f"🗑 {html.escape(who)} (<code>{tg_id}</code>) сброшен. Следующий /start в основном боте — как у нового пользователя.")


@router.message()
async def any_message(msg: Message):
    if not _is_admin(msg):
        await msg.answer("Нет доступа.")
        return
    router.db.add_admin(msg.chat.id, (msg.from_user.username or "").lower())
    await msg.answer("✅ Вы администратор. Сюда будут приходить все результаты обработки.\n"
                     "/drop @username — сбросить пользователя для теста (без аргумента — себя).")


async def notify(admin_bot: Bot | None, db: DB, *, job_id: int, user, request: str, brief: str,
                 price: int, cost_usd: float, seconds: float, original: bytes, src_ext: str, result,
                 ai_op: str | None = None, ai_prompt: str | None = None, ai_ratio: str | None = None,
                 extend_ratio: str | None = None) -> None:
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
    prompt_md = (
        f"# job{job_id} — system prompt\n\n"
        f"- **AI op:** {ai_op or '—'}\n"
        f"- **AI ratio:** {ai_ratio or '—'}\n"
        f"- **Extend:** {extend_ratio or '—'}\n\n"
        f"## Request\n\n{request or '—'}\n\n"
        f"## Brief\n\n{brief or '—'}\n\n"
        f"## Prompt\n\n```text\n{ai_prompt or '—'}\n```\n"
    ).encode()
    media = [
        InputMediaDocument(media=BufferedInputFile(original, filename=f"job{job_id}_before.{src_ext}")),
        InputMediaDocument(media=BufferedInputFile(result.data, filename=f"job{job_id}_after.{result.ext}"),
                           caption=caption, parse_mode="HTML"),
        InputMediaDocument(media=BufferedInputFile(prompt_md, filename=f"job{job_id}_system_prompt.md")),
    ]
    for chat_id in db.admin_chats():
        try:
            await admin_bot.send_media_group(chat_id, media)
        except Exception:
            log.exception("admin notify failed for chat %s", chat_id)
