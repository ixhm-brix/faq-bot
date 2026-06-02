"""Appointment-booking conversation flow.

Multi-turn FSM (name -> phone -> reason -> datetime -> confirm) for orgs whose
institution_type unlocks the "appointments" module. The same module is reused
for clinics, salons, mechanics, consultants, etc. — anywhere people schedule
time slots.

Storage: data/appointments.db (src.appointments).
Staff notification: piggybacks on the existing handoff chat id setting.
Trigger: /book command or a "Book appointment" inline button from /start.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import dateparser
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src import appointments
from src.settings import (
    WEEKDAYS,
    get_handoff_chat_id,
    get_working_hours,
    has_module,
)

log = logging.getLogger("bot.booking")
router = Router(name="booking")

# Use local (system) timezone for slot parsing — the bot is intended to run
# wherever the org operates, and a Rwanda clinic typing "tomorrow 10am" means
# their local 10am, not UTC.
_LOCAL_TZ = ZoneInfo("Africa/Kigali")


class BookingState(StatesGroup):
    name = State()
    phone = State()
    reason = State()
    slot = State()
    confirming = State()


PHONE_RE = re.compile(r"\+?\d[\d\s\-]{5,}")
CANCEL_KEYWORDS = {"cancel", "/cancel", "stop", "/stop"}


def _is_cancel(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in CANCEL_KEYWORDS


async def _abort(message: Message, state: FSMContext, reason: str = "OK, no booking made.") -> None:
    await state.clear()
    await message.answer(reason)


def _parse_slot(text: str) -> datetime | None:
    """Parse a natural-language slot like 'tomorrow at 10am' into an aware datetime
    in the local clinic timezone. Returns None if it can't be parsed or lies in
    the past."""
    parsed = dateparser.parse(
        text,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": "Africa/Kigali",
            "TO_TIMEZONE": "Africa/Kigali",
        },
    )
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_LOCAL_TZ)
    if parsed <= datetime.now(_LOCAL_TZ):
        return None
    return parsed


def _validate_against_hours(slot: datetime) -> tuple[bool, str | None]:
    """Check the slot is within the configured working hours. Returns
    (ok, friendly_reason_if_not_ok)."""
    hours = get_working_hours()
    day_key = WEEKDAYS[slot.weekday()]
    day_window = hours.get(day_key)
    pretty_day = slot.strftime("%A")
    if day_window is None:
        return False, f"We're closed on {pretty_day}s. Try another day."
    open_h, open_m = map(int, day_window["open"].split(":"))
    close_h, close_m = map(int, day_window["close"].split(":"))
    open_t = time(open_h, open_m)
    close_t = time(close_h, close_m)
    if not (open_t <= slot.time() < close_t):
        return (
            False,
            f"On {pretty_day}s we're open {day_window['open']}–{day_window['close']}. Pick a time in that range.",
        )
    return True, None


def _format_slot(slot: datetime) -> str:
    return slot.strftime("%A, %d %b %Y at %H:%M")


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data="book:confirm"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="book:cancel"),
            ]
        ]
    )


def booking_start_keyboard() -> InlineKeyboardMarkup:
    """Used by the suggestion offer in main.py when a user types booking
    intent in normal chat."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Book an appointment", callback_data="book:start")]
        ]
    )


async def _begin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BookingState.name)
    await message.answer(
        "Great — let's book your appointment. (You can type <i>cancel</i> any time to stop.)\n\n"
        "What's your <b>full name</b>?"
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@router.message(Command("book"))
async def cmd_book(message: Message, state: FSMContext) -> None:
    if not has_module("appointments"):
        await message.answer(
            "Appointment booking isn't enabled for this organisation. "
            "An admin can turn it on by setting the institution type in the portal."
        )
        return
    await _begin(message, state)


@router.callback_query(F.data == "book:start")
async def cb_book_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    if not has_module("appointments"):
        await callback.message.answer("Booking isn't enabled here.")
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _begin(callback.message, state)


# ---------------------------------------------------------------------------
# State handlers
# ---------------------------------------------------------------------------


@router.message(BookingState.name)
async def collect_name(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _abort(message, state)
        return
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Please give me your full name (at least 2 characters).")
        return
    await state.update_data(name=name)
    await state.set_state(BookingState.phone)
    await message.answer(
        f"Thanks, {html_lib.escape(name.split()[0])}. What's your <b>phone number</b>?"
    )


@router.message(BookingState.phone)
async def collect_phone(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _abort(message, state)
        return
    phone = (message.text or "").strip()
    if not PHONE_RE.fullmatch(phone):
        await message.answer(
            "That doesn't look like a phone number. Try something like "
            "<code>+250 788 123 456</code>."
        )
        return
    await state.update_data(phone=phone)
    await state.set_state(BookingState.reason)
    await message.answer(
        "Got it. What's the <b>reason</b> for the appointment? (a short description is fine)"
    )


@router.message(BookingState.reason)
async def collect_reason(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _abort(message, state)
        return
    reason = (message.text or "").strip()
    if len(reason) < 2:
        await message.answer("Please give me a brief reason for the visit.")
        return
    await state.update_data(reason=reason)
    await state.set_state(BookingState.slot)
    await message.answer(
        "When would you like to come in? Try something like "
        "<code>tomorrow at 10am</code>, <code>next Monday at 14:00</code>, "
        "or <code>9 Jun at 09:30</code>."
    )


@router.message(BookingState.slot)
async def collect_slot(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _abort(message, state)
        return
    text = (message.text or "").strip()
    slot = _parse_slot(text)
    if slot is None:
        await message.answer(
            "I couldn't read that as a future date and time. "
            "Try something like <code>tomorrow at 10am</code> or <code>9 Jun 09:30</code>."
        )
        return
    ok, reason_msg = _validate_against_hours(slot)
    if not ok:
        await message.answer(reason_msg or "Please pick a time within our working hours.")
        return
    await state.update_data(
        slot_iso=slot.isoformat(timespec="minutes"),
        slot_display=_format_slot(slot),
    )
    await state.set_state(BookingState.confirming)
    data = await state.get_data()
    summary = (
        "Here's what I've got — please confirm:\n\n"
        f"<b>Name:</b> {html_lib.escape(data['name'])}\n"
        f"<b>Phone:</b> {html_lib.escape(data['phone'])}\n"
        f"<b>Reason:</b> {html_lib.escape(data['reason'])}\n"
        f"<b>When:</b> {html_lib.escape(data['slot_display'])}"
    )
    await message.answer(summary, reply_markup=_confirm_keyboard())


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


async def _notify_staff(bot: Bot, appointment_id: int, data: dict, user) -> None:
    chat_id = get_handoff_chat_id()
    if not chat_id:
        return
    handle = f"@{user.username}" if user and user.username else None
    name_line = f"{html_lib.escape(data['name'])}"
    if handle:
        name_line += f" ({handle})"
    body = (
        f"📅 <b>New appointment #{appointment_id}</b>\n\n"
        f"<b>Name:</b> {name_line}\n"
        f"<b>Phone:</b> {html_lib.escape(data['phone'])}\n"
        f"<b>Reason:</b> {html_lib.escape(data['reason'])}\n"
        f"<b>When:</b> {html_lib.escape(data['slot_display'])}\n\n"
        "Confirm or update the booking in the portal."
    )
    try:
        await bot.send_message(chat_id=chat_id, text=body)
    except Exception:
        log.exception("Failed to send appointment notification to staff chat %s", chat_id)


@router.callback_query(F.data == "book:confirm", BookingState.confirming)
async def cb_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    user = callback.from_user
    appointment_id = appointments.record(
        name=data["name"],
        phone=data["phone"],
        reason=data["reason"],
        slot_iso=data["slot_iso"],
        slot_display=data["slot_display"],
        user_chat_id=callback.message.chat.id,
        user_username=user.username if user else None,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Booked! Your appointment is on <b>{html_lib.escape(data['slot_display'])}</b>. "
        "Our team will confirm with you shortly. To change or cancel, just contact us."
    )
    await _notify_staff(callback.message.bot, appointment_id, data, user)
    await state.clear()


@router.callback_query(F.data == "book:cancel", BookingState.confirming)
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer("No problem — booking cancelled.")


# Catch-all when in any booking state: stops normal FAQ handling.
@router.message(BookingState.confirming)
async def confirming_unexpected(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _abort(message, state)
        return
    await message.answer(
        "Please tap <b>Confirm</b> or <b>Cancel</b> above, or type <i>cancel</i> to abort."
    )


# ---------------------------------------------------------------------------
# Intent detection (called from main.py before the catch-all)
# ---------------------------------------------------------------------------


_BOOKING_KEYWORDS = re.compile(
    r"\b(book|booking|appointment|appointments|schedule|reserve|reservation|rendez[- ]?vous)\b",
    re.IGNORECASE,
)


def detect_booking_intent(text: str) -> bool:
    return bool(_BOOKING_KEYWORDS.search(text or ""))
