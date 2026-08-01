import json
from pathlib import Path

SETTINGS_PATH = Path("data/settings.json")
DEFAULT_BOT_NAME = "FAQ Assistant"


def _load() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_telegram_bot_token() -> str:
    val = _load().get("telegram_bot_token", "")
    return val.strip() if isinstance(val, str) else ""


def set_telegram_bot_token(raw: str) -> None:
    data = _load()
    data["telegram_bot_token"] = (raw or "").strip()
    _save(data)


def is_setup_complete() -> bool:
    return bool(_load().get("setup_complete", False))


def mark_setup_complete() -> None:
    data = _load()
    data["setup_complete"] = True
    _save(data)


def auto_mark_setup_if_existing() -> None:
    """Treat a settings.json that already has user configuration as a completed
    setup, so existing deployments aren't bounced to the wizard after upgrade."""
    data = _load()
    if data.get("setup_complete"):
        return
    has_state = bool(
        data.get("bot_name")
        or data.get("institution_type")
        or data.get("handoff_chat_id")
        or data.get("suggested_questions")
        or data.get("telegram_bot_token")
    )
    if has_state:
        data["setup_complete"] = True
        _save(data)


def get_bot_name() -> str:
    name = _load().get("bot_name", "").strip()
    return name or DEFAULT_BOT_NAME


def set_bot_name(name: str) -> None:
    data = _load()
    data["bot_name"] = name.strip() or DEFAULT_BOT_NAME
    _save(data)


def get_handoff_chat_id() -> int | None:
    val = _load().get("handoff_chat_id")
    if val in (None, ""):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def set_handoff_chat_id(raw: str) -> None:
    data = _load()
    v = (raw or "").strip()
    if not v:
        data["handoff_chat_id"] = None
    else:
        try:
            data["handoff_chat_id"] = int(v)
        except ValueError:
            data["handoff_chat_id"] = None
    _save(data)


def get_suggested_questions() -> list[str]:
    val = _load().get("suggested_questions")
    if isinstance(val, list):
        return [str(q) for q in val if isinstance(q, str) and q.strip()]
    return []


def set_suggested_questions(questions: list[str]) -> None:
    data = _load()
    data["suggested_questions"] = [q.strip() for q in questions if q and q.strip()]
    _save(data)


DEFAULT_RETRIEVAL_THRESHOLD = 1.8
RETRIEVAL_THRESHOLD_MIN = 0.5
RETRIEVAL_THRESHOLD_MAX = 2.5


def get_retrieval_threshold() -> float:
    raw = _load().get("retrieval_threshold")
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_RETRIEVAL_THRESHOLD
    if RETRIEVAL_THRESHOLD_MIN <= f <= RETRIEVAL_THRESHOLD_MAX:
        return f
    return DEFAULT_RETRIEVAL_THRESHOLD


def set_retrieval_threshold(raw: str) -> None:
    data = _load()
    try:
        f = float(raw)
        if RETRIEVAL_THRESHOLD_MIN <= f <= RETRIEVAL_THRESHOLD_MAX:
            data["retrieval_threshold"] = f
        else:
            data["retrieval_threshold"] = DEFAULT_RETRIEVAL_THRESHOLD
    except (TypeError, ValueError):
        data["retrieval_threshold"] = DEFAULT_RETRIEVAL_THRESHOLD
    _save(data)


# --- WhatsApp channel (via Twilio for now) -------------------------------

def get_whatsapp_account_sid() -> str:
    val = _load().get("whatsapp_account_sid", "")
    return val.strip() if isinstance(val, str) else ""


def get_whatsapp_auth_token() -> str:
    val = _load().get("whatsapp_auth_token", "")
    return val.strip() if isinstance(val, str) else ""


def get_whatsapp_from_number() -> str:
    """The Twilio WhatsApp 'from' number, e.g. 'whatsapp:+14155238886'
    for the sandbox or your own WA-enabled Twilio number."""
    val = _load().get("whatsapp_from_number", "")
    return val.strip() if isinstance(val, str) else ""


def get_whatsapp_public_url() -> str:
    """The exact public URL Twilio is configured to call for the webhook,
    e.g. 'https://abc123.ngrok.io/whatsapp/webhook'. Used to validate the
    request signature: Twilio signs against the URL it dialled, which can
    differ from the URL the app sees behind a proxy/tunnel (http vs https,
    internal host). Empty means 'trust the URL the request arrived on'."""
    val = _load().get("whatsapp_public_url", "")
    return val.strip() if isinstance(val, str) else ""


def whatsapp_configured() -> bool:
    return all(
        [get_whatsapp_account_sid(), get_whatsapp_auth_token(), get_whatsapp_from_number()]
    )


def set_whatsapp_settings(
    account_sid: str, auth_token: str, from_number: str, public_url: str | None = None
) -> None:
    data = _load()
    data["whatsapp_account_sid"] = (account_sid or "").strip()
    if auth_token and auth_token.strip():
        # Empty submit means "leave it alone" so admins don't have to
        # re-paste the secret every time they tweak another field.
        data["whatsapp_auth_token"] = auth_token.strip()
    from_number = (from_number or "").strip()
    if from_number and not from_number.startswith("whatsapp:"):
        from_number = f"whatsapp:{from_number}"
    data["whatsapp_from_number"] = from_number
    if public_url is not None:
        data["whatsapp_public_url"] = public_url.strip()
    _save(data)


# --- Institution type & per-vertical optional modules --------------------

# Each option maps to: (display label, modules unlocked).
# "appointments" unlocks the booking flow for orgs that schedule visits.
INSTITUTION_TYPES: dict[str, tuple[str, set[str]]] = {
    "generic": ("General organization", set()),
    "clinic": ("Clinic / Hospital", {"appointments"}),
    "salon": ("Salon / Spa", {"appointments"}),
    "mechanic": ("Mechanic / Auto shop", {"appointments"}),
    "consultant": ("Consultant / Coach", {"appointments"}),
    "school": ("School / University", set()),
    "event": ("Event organizer", set()),
    "government": ("Government / Public office", set()),
    "other": ("Other", set()),
}
DEFAULT_INSTITUTION_TYPE = "generic"


def get_institution_type() -> str:
    val = _load().get("institution_type")
    if isinstance(val, str) and val in INSTITUTION_TYPES:
        return val
    return DEFAULT_INSTITUTION_TYPE


def set_institution_type(raw: str) -> None:
    data = _load()
    v = (raw or "").strip().lower()
    data["institution_type"] = v if v in INSTITUTION_TYPES else DEFAULT_INSTITUTION_TYPE
    _save(data)


def has_module(module: str) -> bool:
    _, modules = INSTITUTION_TYPES[get_institution_type()]
    return module in modules


# --- Working hours (used by the appointments module) ---------------------

# Per-weekday: either None (closed) or {"open": "HH:MM", "close": "HH:MM"}.
# Keys are the lowercase three-letter weekday names.
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_WORKING_HOURS: dict[str, dict[str, str] | None] = {
    "mon": {"open": "08:00", "close": "18:00"},
    "tue": {"open": "08:00", "close": "18:00"},
    "wed": {"open": "08:00", "close": "18:00"},
    "thu": {"open": "08:00", "close": "18:00"},
    "fri": {"open": "08:00", "close": "18:00"},
    "sat": {"open": "09:00", "close": "14:00"},
    "sun": None,
}


def _valid_hhmm(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        return False
    try:
        h, m = int(s[:2]), int(s[3:])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def get_working_hours() -> dict[str, dict[str, str] | None]:
    raw = _load().get("working_hours")
    if not isinstance(raw, dict):
        return dict(DEFAULT_WORKING_HOURS)
    out: dict[str, dict[str, str] | None] = {}
    for day in WEEKDAYS:
        v = raw.get(day)
        if isinstance(v, dict) and _valid_hhmm(v.get("open", "")) and _valid_hhmm(v.get("close", "")):
            out[day] = {"open": v["open"], "close": v["close"]}
        else:
            out[day] = None
    return out


def set_working_hours(form: dict[str, str]) -> None:
    """Accept a flat form payload from the portal: e.g. {"mon_open": "08:00",
    "mon_close": "18:00", "sun_closed": "on", ...}. Days flagged closed (or
    with invalid times) are stored as None."""
    data = _load()
    hours: dict[str, dict[str, str] | None] = {}
    for day in WEEKDAYS:
        if form.get(f"{day}_closed"):
            hours[day] = None
            continue
        o = form.get(f"{day}_open", "").strip()
        c = form.get(f"{day}_close", "").strip()
        if _valid_hhmm(o) and _valid_hhmm(c) and o < c:
            hours[day] = {"open": o, "close": c}
        else:
            hours[day] = None
    data["working_hours"] = hours
    _save(data)
