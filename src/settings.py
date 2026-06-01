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
