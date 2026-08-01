import asyncio
import html as html_lib
import logging
import os
import secrets
import tempfile
from collections import OrderedDict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src import chat, handoff
from src.transcribe import transcribe
from src.bot.booking import (
    booking_start_keyboard,
    detect_booking_intent,
    router as booking_router,
)
from src.bot.format import md_to_html
from src.config import TELEGRAM_BOT_TOKEN
from src.llm import generate_followups
from src.memory import remember_message
from src.rag.retrieve import RetrievedChunk
from src.settings import (
    get_bot_name,
    get_handoff_chat_id,
    get_suggested_questions,
    get_telegram_bot_token,
    has_module,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

dp = Dispatcher()

_followup_cache: "OrderedDict[str, str]" = OrderedDict()
_FOLLOWUP_CACHE_MAX = 500


def _remember_followup(question: str) -> str:
    token = secrets.token_urlsafe(6)
    _followup_cache[token] = question
    while len(_followup_cache) > _FOLLOWUP_CACHE_MAX:
        _followup_cache.popitem(last=False)
    return token


def _pop_followup(token: str) -> str | None:
    return _followup_cache.pop(token, None)


def _followups_keyboard(questions: list[str]) -> InlineKeyboardMarkup | None:
    if not questions:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=q, callback_data=f"fu:{_remember_followup(q)}")]
            for q in questions
        ]
    )


def _start_keyboard() -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if has_module("appointments"):
        rows.append(
            [InlineKeyboardButton(text="📅 Book an appointment", callback_data="book:start")]
        )
    questions = get_suggested_questions()
    for i, q in enumerate(questions):
        rows.append([InlineKeyboardButton(text=q, callback_data=f"ask:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@dp.message(CommandStart())
async def on_start(message: Message) -> None:
    name = get_bot_name()
    keyboard = _start_keyboard()
    if keyboard:
        text = (
            f"Hi! I'm {name}, your FAQ assistant. Ask me anything about the "
            "organization, or tap one of these to get started:"
        )
    else:
        text = (
            f"Hi! I'm {name}, your FAQ assistant. Ask me anything about the organization."
        )
    await message.answer(text, reply_markup=keyboard)


@dp.message(Command("myid"))
async def on_myid(message: Message) -> None:
    await message.answer(
        f"This chat's ID is: <code>{message.chat.id}</code>\n\n"
        "If you're a staff member setting up handoff, paste this ID into the "
        "<b>Receptionist Telegram chat ID</b> field on the portal."
    )


async def _keep_typing(bot: Bot, chat_id: int, stop_event: asyncio.Event) -> None:
    """Re-send the typing action every ~4s so the indicator stays visible
    even for slow LLM responses (Telegram's typing action expires after 5s)."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.0)
            return
        except asyncio.TimeoutError:
            continue


async def _forward_handoff_to_staff(
    bot: Bot, user, text: str, handoff_id: int
) -> bool:
    staff_chat_id = get_handoff_chat_id()
    if not staff_chat_id:
        return False
    handle = f"@{user.username}" if user and user.username else None
    name = user.full_name if user else "(unknown)"
    contact_line = f"{name}" + (f" ({handle})" if handle else "")
    body = (
        f"\U0001F198 <b>Handoff #{handoff_id}</b>\n\n"
        f"<b>From:</b> {html_lib.escape(contact_line)}\n"
        f"<b>Question:</b>\n<i>{html_lib.escape(text)}</i>\n\n"
        "Reply to the user directly on Telegram. Mark resolved in the portal when done."
    )
    try:
        await bot.send_message(chat_id=staff_chat_id, text=body)
        return True
    except Exception:
        log.exception("Failed to forward handoff to staff chat %s", staff_chat_id)
        return False


async def _enrich_with_followups(
    bot: Bot,
    chat_id: int,
    message_id: int,
    user_question: str,
    assistant_reply: str,
    chunks: list[RetrievedChunk],
) -> None:
    """Generate follow-up buttons in the background and attach them to the reply."""
    try:
        followups = await generate_followups(user_question, assistant_reply, chunks)
    except Exception:
        log.exception("Failed to generate followups")
        return
    keyboard = _followups_keyboard(followups)
    if not keyboard:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=keyboard
        )
    except Exception:
        log.exception("Failed to attach followups keyboard")


async def _process_question(bot: Bot, chat_id: int, user, text: str) -> None:
    # Fire typing IMMEDIATELY so the user sees feedback within ~100ms,
    # before any sqlite/embedding/LLM work that would otherwise delay it.
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    # Booking intent shortcut: if the user mentions booking/appointment
    # and the module is enabled, offer the booking button instead of
    # running a full RAG round-trip on a question we can't answer well.
    if has_module("appointments") and detect_booking_intent(text):
        await bot.send_message(
            chat_id,
            "Looks like you'd like to book an appointment — tap below to start:",
            reply_markup=booking_start_keyboard(),
        )
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(bot, chat_id, stop_typing))

    final: str | None = None
    chunks_used: list[RetrievedChunk] = []
    try:
        result = await chat.answer_message(str(chat_id), text)
        if result.is_security:
            # Prompt-injection / jailbreak attempt — refuse, don't escalate.
            final = chat.build_security_reply()
            remember_message(chat_id, "assistant", final)
        elif result.is_off_topic:
            # Off-topic questions don't get handed to staff — that would
            # waste their time. Polite decline only.
            final = chat.build_off_topic_reply()
            remember_message(chat_id, "assistant", final)
        elif result.is_handoff:
            handoff_id = handoff.record(
                question=text,
                user_chat_id=chat_id,
                user_username=user.username if user else None,
                user_full_name=user.full_name if user else None,
            )
            forwarded = await _forward_handoff_to_staff(
                bot, user, text, handoff_id
            )
            if result.text:
                # Partial answer: give the user what we know; the team still
                # gets the question to resolve the unknown part.
                final = result.text
            else:
                final = (
                    "I couldn't find that in our documents, so I've passed your "
                    "question to our team. Someone will get back to you shortly."
                    if forwarded
                    else "I couldn't find that in our documents. Your question has "
                    "been logged for our team to follow up on."
                )
            # Channel-specific handoff phrasing — store it as the assistant
            # turn so the next message has accurate context.
            remember_message(chat_id, "assistant", final)
        else:
            final = result.text
            chunks_used = result.chunks_used
    except Exception:
        log.exception("RAG/LLM call failed")
        final = None
    finally:
        stop_typing.set()
        await typing_task

    if final is None:
        await bot.send_message(
            chat_id, "Sorry, something went wrong. Please try again in a moment."
        )
        return

    sent = await bot.send_message(chat_id, md_to_html(final))

    if chunks_used:
        asyncio.create_task(
            _enrich_with_followups(
                bot, chat_id, sent.message_id, text, final, chunks_used
            )
        )


@dp.callback_query(F.data.startswith("ask:"))
async def on_suggestion(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        idx = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    questions = get_suggested_questions()
    if not 0 <= idx < len(questions):
        return
    question = questions[idx]

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(
            f"<i>You asked:</i> {html_lib.escape(question)}"
        )
        chat_id = callback.message.chat.id
        bot = callback.message.bot
    else:
        return

    await _process_question(bot, chat_id, callback.from_user, question)


@dp.callback_query(F.data.startswith("fu:"))
async def on_followup(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.data or not callback.message:
        return
    token = callback.data.split(":", 1)[1]
    question = _pop_followup(token)
    if not question:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"<i>You asked:</i> {html_lib.escape(question)}"
    )
    await _process_question(
        callback.message.bot,
        callback.message.chat.id,
        callback.from_user,
        question,
    )


# Registered BEFORE on_message so voice/audio notes route here instead of
# hitting the text catch-all. StateFilter(None) keeps it out of the booking
# FSM — a voice note mid-booking falls through to the booking router.
@dp.message(StateFilter(None), F.voice | F.audio)
async def on_voice(message: Message) -> None:
    bot = message.bot
    chat_id = message.chat.id
    media = message.voice or message.audio
    if media is None:
        return

    # Immediate feedback — the first transcription also loads the Whisper
    # model (a one-time download), so this can take a few seconds.
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await bot.download(media.file_id, destination=tmp_path)
        text = await transcribe(tmp_path)
    except Exception:
        log.exception("Voice handling failed")
        text = ""
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if not text:
        await message.answer(
            "Sorry, I couldn't make out that voice note. Could you try again, "
            "or type your question?"
        )
        return

    # Show what we heard so the user can catch a mis-transcription, then run
    # the transcript through the exact same pipeline as a typed message.
    await message.answer(f"\U0001F3A4 <i>I heard:</i> {html_lib.escape(text)}")
    await _process_question(bot, chat_id, message.from_user, text)


@dp.message(StateFilter(None))
async def on_message(message: Message) -> None:
    if not message.text:
        await message.answer("I can only handle text and voice messages for now.")
        return
    await _process_question(
        message.bot, message.chat.id, message.from_user, message.text
    )


async def main() -> None:
    # Prefer the token set through the portal; fall back to the legacy .env
    # value so existing deployments keep working without a config migration.
    token = get_telegram_bot_token() or TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError(
            "Telegram bot token is not configured. Set it in the portal "
            "(Settings → Telegram bot token) or in TELEGRAM_BOT_TOKEN in .env."
        )
    dp.include_router(booking_router)
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
