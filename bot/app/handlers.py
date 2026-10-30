import asyncio
import json
import logging
import time
from dataclasses import replace

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import admin, extend, pipeline, texts
from .config import config
from .db import DB
from .llm import GigaChat
from .plan import Plan, PlanError, ai_ratio_fits, drop_unasked_enhance, fix_stretch, nearest_ai_ratio, orientation_warning, parse_plan, ratio_crop_warning
from .providers import ImageEditProvider

log = logging.getLogger(__name__)
router = Router()
MAX_FILE = 20 * 1024 * 1024


class S(StatesGroup):
    waiting_task = State()
    waiting_edit = State()


def setup(db: DB, llm: GigaChat, provider: ImageEditProvider, admin_bot: Bot | None = None):
    router.db, router.llm, router.provider, router.admin_bot = db, llm, provider, admin_bot  # simple DI


def _db() -> DB:
    return router.db


def _kb(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"ok:{job_id}"),
                InlineKeyboardButton(text="✏️ Поправить", callback_data=f"edit:{job_id}"),
            ]
        ]
    )


def _user(msg: Message, source: str | None = None) -> bool:
    return _db().ensure_user(msg.from_user.id, msg.from_user.username, source, config.welcome_bonus)


@router.message(CommandStart())
async def start(msg: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    source = (command.args or "direct")[:64]
    is_new = _user(msg, source)
    _db().event(msg.from_user.id, "start", source=source, new=is_new)
    await msg.answer(texts.WELCOME if is_new else texts.WELCOME_BACK)


@router.message(Command("help"))
async def help_(msg: Message):
    _user(msg)
    await msg.answer(texts.HELP)


@router.message(Command("balance"))
async def balance(msg: Message):
    _user(msg)
    await msg.answer(texts.balance(_db().balance(msg.from_user.id)))


@router.message(F.photo | F.document)
async def on_image(msg: Message, bot: Bot, state: FSMContext):
    _user(msg)
    if msg.photo:
        file = msg.photo[-1]
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file = msg.document
    else:
        await msg.answer(texts.NOT_IMAGE)
        return
    if (file.file_size or 0) > MAX_FILE:
        await msg.answer(texts.TOO_BIG)
        return
    data = (await bot.download(file.file_id)).read()
    try:
        info = pipeline.describe(data)
    except Exception:
        await msg.answer(texts.NOT_IMAGE)
        return
    info["sent_as"] = "photo (compressed by Telegram)" if msg.photo else "file"
    job_id = _db().create_job(msg.from_user.id, file.file_id, info)
    _db().event(msg.from_user.id, "image_received", job_id=job_id, **{k: info[k] for k in ("width", "height", "format", "size_kb")})
    if msg.caption:
        await make_brief(msg, state, job_id, msg.caption)
    else:
        await state.set_state(S.waiting_task)
        await state.update_data(job_id=job_id)
        await msg.answer(texts.ASK_TASK)


@router.message(S.waiting_task, F.text)
async def on_task(msg: Message, state: FSMContext):
    job_id = (await state.get_data())["job_id"]
    await make_brief(msg, state, job_id, msg.text)


@router.message(S.waiting_edit, F.text)
async def on_edit_text(msg: Message, state: FSMContext):
    job_id = (await state.get_data())["job_id"]
    await make_brief(msg, state, job_id, msg.text, is_edit=True)


@router.message(F.text)
async def on_text(msg: Message):
    _user(msg)
    await msg.answer(texts.NEED_IMAGE)


async def make_brief(msg: Message, state: FSMContext, job_id: int, request: str, is_edit: bool = False):
    db = _db()
    job = db.get_job(job_id)
    if job["iterations"] >= config.max_brief_iterations:
        await state.clear()
        await msg.answer(texts.TOO_MANY_EDITS)
        return
    prev = json.loads(job["plan"]) if (is_edit and job["plan"]) else None
    asked = None
    if prev:
        prev.pop("ai_prompt", None)  # rendered in code; the LLM only picks ai_op
        prev.pop("ai_ratio", None)  # legacy field
        asked = prev.pop("question", None)  # the bot's own clarification, not part of the plan
    wait = await msg.answer(texts.THINKING)
    try:
        plan, tokens = await router.llm.make_plan(json.loads(job["image_info"]), request, prev)
    except (PlanError, Exception) as e:
        log.exception("brief failed: %s", e)
        db.event(msg.from_user.id, "brief_failed", job_id=job_id, error=str(e)[:200])
        await wait.edit_text(texts.LLM_ERROR)
        return
    # Stored for the admin log only; the LLM receives `request`, not this string.
    full_request = f"{job['request']}\n\nУточнение: {request}" if (is_edit and job["request"]) else request
    info = json.loads(job["image_info"])
    # fix_stretch first: an AI plan (even enhance-only) gets AI extend instead of padding.
    plan = drop_unasked_enhance(fix_stretch(plan, full_request, info["width"], info["height"]), full_request)
    size = pipeline.output_size(info["width"], info["height"], plan.ops, plan.extend)
    warn = orientation_warning(plan, full_request, size) or ratio_crop_warning(plan, full_request, info["width"], info["height"])
    if warn and warn != asked:  # ask once; the user's answer settles it
        plan = replace(plan, question=warn)
    db.update_job(job_id, request=full_request, plan=json.dumps(plan.to_dict(), ensure_ascii=False), iterations=job["iterations"] + 1)
    db.add_job_cost(job_id, llm_tokens=tokens)
    await state.update_data(job_id=job_id)

    if plan.refuse:
        db.update_job(job_id, status="refused", finished_at=int(time.time()))
        db.event(msg.from_user.id, "refused", job_id=job_id, reason=plan.refuse[:200])
        await state.clear()
        await wait.edit_text(f"🚫 {plan.refuse}")
        return
    if plan.question or not plan.actionable:
        await state.set_state(S.waiting_edit)
        db.event(msg.from_user.id, "clarify", job_id=job_id)
        await wait.edit_text(f"❓ {plan.question or plan.brief}")
        return
    await state.set_state(None)
    db.event(msg.from_user.id, "brief_shown", job_id=job_id, iteration=job["iterations"] + 1, ai=plan.is_ai, price=plan.price)
    await wait.edit_text(texts.brief(plan.brief, plan.price, size), reply_markup=_kb(job_id))


@router.callback_query(F.data.startswith("edit:"))
async def on_edit(cb: CallbackQuery, state: FSMContext):
    job_id = int(cb.data.split(":")[1])
    job = _db().get_job(job_id)
    if not job or job["tg_id"] != cb.from_user.id or job["status"] != "draft":
        await cb.answer()
        return
    await state.set_state(S.waiting_edit)
    await state.update_data(job_id=job_id)
    _db().event(cb.from_user.id, "brief_edit", job_id=job_id)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.EDIT_PROMPT)
    await cb.answer()


@router.callback_query(F.data.startswith("ok:"))
async def on_confirm(cb: CallbackQuery, bot: Bot, state: FSMContext):
    db = _db()
    uid = cb.from_user.id
    job_id = int(cb.data.split(":")[1])
    job = db.get_job(job_id)
    if not job or job["tg_id"] != uid or not job["plan"]:
        await cb.answer()
        return
    plan: Plan = parse_plan(json.loads(job["plan"]))
    bal = db.balance(uid)
    if bal < plan.price:
        db.event(uid, "insufficient_balance", job_id=job_id, price=plan.price, balance=bal)
        await cb.answer()
        await cb.message.answer(texts.no_money(plan.price, bal))
        return
    if not db.claim_job(job_id, uid):
        await cb.answer()
        return
    await cb.answer()
    await state.clear()
    await cb.message.edit_reply_markup(reply_markup=None)
    db.event(uid, "confirmed", job_id=job_id, ai=plan.is_ai, price=plan.price)
    wait = await cb.message.answer(texts.WORKING)
    t0 = time.time()
    try:
        image_info = json.loads(job["image_info"])
        data = original = (await bot.download(job["file_id"])).read()
        cost_usd = 0.0
        ai_ratio = None

        async def ai_edit(data: bytes, width: int, height: int) -> bytes:
            nonlocal cost_usd, ai_ratio
            # The AI step never changes framing: its output ratio is the input ratio.
            ai_ratio = nearest_ai_ratio(width, height)
            ai = await router.provider.edit(data, plan.ai_prompt, ai_ratio)
            db.add_job_cost(job_id, provider_cost_usd=ai.cost_usd)
            cost_usd += ai.cost_usd
            return ai.data

        # AI edits are unstable, so they run last. Exception: an extended image wider than the
        # model's ratios (21:9 / 9:16) cannot be edited as a whole; then the edit runs first.
        ext_size = pipeline.output_size(image_info["width"], image_info["height"], [], plan.extend)
        edit_last = bool(plan.ai_prompt and plan.extend and ai_ratio_fits(*ext_size))
        if plan.ai_prompt and not edit_last:
            data = await ai_edit(data, image_info["width"], image_info["height"])
        if plan.extend:
            img, ext_cost, calls = await extend.extend(router.provider, data, plan.extend)
            db.add_job_cost(job_id, provider_cost_usd=ext_cost)
            cost_usd += ext_cost
            data = pipeline.encode(img, "png").data
            db.event(uid, "extended", job_id=job_id, ratio=plan.extend, calls=calls, cost_usd=round(ext_cost, 4))
            if edit_last:
                data = await ai_edit(data, img.width, img.height)
        src_fmt = image_info.get("format")
        res = await asyncio.to_thread(pipeline.run, data, plan.ops, "jpeg" if src_fmt == "mpo" else src_fmt)
    except Exception as e:
        log.exception("job %s failed", job_id)
        db.update_job(job_id, status="failed", error=str(e)[:500], finished_at=int(time.time()))
        db.event(uid, "failed", job_id=job_id, error=str(e)[:200])
        await wait.edit_text(texts.FAILED)
        return
    new_bal = db.charge(uid, plan.price, job_id)
    db.update_job(job_id, status="done", price=plan.price, finished_at=int(time.time()))
    seconds = round(time.time() - t0, 1)
    db.event(uid, "delivered", job_id=job_id, ai=plan.is_ai, price=plan.price, seconds=seconds,
             width=res.width, height=res.height, kb=res.kb, fmt=res.fmt)
    await wait.delete()
    await cb.message.answer_document(
        BufferedInputFile(res.data, filename=f"imgrsz_{job_id}.{res.ext}"),
        caption=texts.done(res, plan.price, new_bal, plan.is_ai),
    )
    asyncio.create_task(admin.notify(
        router.admin_bot, db, job_id=job_id, user=cb.from_user, request=job["request"] or "", brief=plan.brief,
        price=plan.price, cost_usd=cost_usd, seconds=seconds, original=original,
        src_ext={"jpeg": "jpg", "mpo": "jpg", "heif": "heic"}.get(src_fmt, src_fmt or "bin"), result=res,
        ai_op=plan.ai_op, ai_prompt=plan.ai_prompt, ai_ratio=ai_ratio, extend_ratio=plan.extend, ops=plan.ops,
    ))
