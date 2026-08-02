import hmac
import json
import logging
import shutil
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from src.config import (
    PORTAL_ADMIN_PASSWORD,
    PORTAL_ADMIN_USERNAME,
    PORTAL_SESSION_SECRET,
    WIDGET_API_KEY,
)
from src import appointments, auth, chat, guards, handoff, handoff_link
from src.kb import kb_is_stale, kb_text
from src.llm import BOT_NAME
from src.settings import (
    INSTITUTION_TYPES,
    WEEKDAYS,
    get_bot_name,
    get_handoff_chat_id,
    get_institution_type,
    get_retrieval_threshold,
    get_suggested_questions,
    get_telegram_bot_token,
    get_timezone,
    get_whatsapp_account_sid,
    get_whatsapp_auth_token,
    get_whatsapp_from_number,
    get_whatsapp_public_url,
    get_working_hours,
    has_module,
    is_setup_complete,
    mark_setup_complete,
    set_bot_name,
    set_handoff_chat_id,
    set_institution_type,
    set_retrieval_threshold,
    set_suggested_questions,
    set_telegram_bot_token,
    set_timezone,
    set_whatsapp_settings,
    set_working_hours,
    whatsapp_configured,
)

PDF_DIR = Path("data/pdfs")
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("portal")

app = FastAPI(title="FAQ Bot Portal")
app.add_middleware(SessionMiddleware, secret_key=PORTAL_SESSION_SECRET)

# The website widget is embedded on third-party origins, so the /widget/*
# endpoints need CORS. Wide-open for the MVP; tighten to per-org allow-list
# when multi-tenancy lands.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=86400,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Seed the initial admin from legacy env credentials so existing deployments
# keep working. Fresh installs without env creds will see the /signup screen.
auth.bootstrap_admin(PORTAL_ADMIN_USERNAME, PORTAL_ADMIN_PASSWORD)

# Existing deployments already have bot_name / institution_type / etc. in
# settings.json — don't bounce those admins to the /setup wizard on upgrade.
from src.settings import auto_mark_setup_if_existing  # noqa: E402
auto_mark_setup_if_existing()

if not WIDGET_API_KEY:
    log.warning(
        "WIDGET_API_KEY is not set — POST /widget/chat is UNAUTHENTICATED. "
        "Set WIDGET_API_KEY in .env to require an X-API-Key header."
    )


def is_authed(request: Request) -> bool:
    return bool(request.session.get("user"))


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if is_authed(request):
        return RedirectResponse("/dashboard", status_code=303)
    if auth.user_count() == 0:
        return RedirectResponse("/signup", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if is_authed(request):
        return RedirectResponse("/dashboard", status_code=303)
    if auth.user_count() == 0:
        return RedirectResponse("/signup", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"user": None, "error": None}
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if auth.verify_password(username, password):
        request.session["user"] = username.strip().lower()
        target = "/dashboard" if is_setup_complete() else "/setup"
        return RedirectResponse(target, status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"user": None, "error": "Invalid username or password."},
        status_code=401,
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    if auth.user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "signup.html", {"user": None, "error": None}
    )


@app.post("/signup")
async def signup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if auth.user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    if password != password_confirm:
        return templates.TemplateResponse(
            request, "signup.html",
            {"user": None, "error": "Passwords don't match."},
            status_code=400,
        )
    try:
        auth.create_user(username, password)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "signup.html",
            {"user": None, "error": str(e)},
            status_code=400,
        )
    request.session["user"] = username.strip().lower()
    return RedirectResponse("/setup", status_code=303)


@app.get("/setup", response_class=HTMLResponse)
async def setup_form(request: Request):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "user": request.session.get("user"),
            "institution_type": get_institution_type(),
            "institution_types": [
                (key, label) for key, (label, _) in INSTITUTION_TYPES.items()
            ],
            "telegram_bot_token": get_telegram_bot_token(),
            "bot_name": get_bot_name(),
            "handoff_chat_id": get_handoff_chat_id() or "",
            "setup_complete": is_setup_complete(),
        },
    )


@app.post("/setup")
async def setup_submit(
    request: Request,
    institution_type: str = Form(...),
    telegram_bot_token: str = Form(""),
    bot_name: str = Form(...),
    handoff_chat_id: str = Form(""),
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    set_institution_type(institution_type)
    if telegram_bot_token.strip():
        set_telegram_bot_token(telegram_bot_token)
    set_bot_name(bot_name)
    set_handoff_chat_id(handoff_chat_id)
    mark_setup_complete()
    return RedirectResponse(
        "/dashboard?message=Setup+saved.+Next+step%3A+upload+a+PDF.",
        status_code=303,
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    if not is_setup_complete():
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": request.session.get("user"),
            "kb_chars": len(kb_text()),
            "kb_stale": kb_is_stale(),
            "api_calls_today": guards.breaker.status(),
            "bot_name": get_bot_name(),
            "telegram_bot_token": get_telegram_bot_token(),
            "whatsapp_account_sid": get_whatsapp_account_sid(),
            "whatsapp_from_number": get_whatsapp_from_number(),
            "whatsapp_public_url": get_whatsapp_public_url(),
            "whatsapp_configured": whatsapp_configured(),
            "timezone": get_timezone(),
            "handoff_chat_id": get_handoff_chat_id() or "",
            "retrieval_threshold": f"{get_retrieval_threshold():.2f}",
            "open_handoffs": handoff.open_count(),
            "pending_appointments": appointments.pending_count(),
            "suggestions": get_suggested_questions(),
            "institution_type": get_institution_type(),
            "institution_types": [
                (key, label) for key, (label, _) in INSTITUTION_TYPES.items()
            ],
            "appointments_enabled": has_module("appointments"),
            "working_hours": get_working_hours(),
            "weekdays": WEEKDAYS,
            "weekday_labels": {
                "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
                "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
                "sun": "Sunday",
            },
            "message": message,
            "error": error,
        },
    )


@app.post("/settings")
async def update_settings(request: Request):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if "bot_name" in form:
        set_bot_name(form.get("bot_name", ""))
    if "handoff_chat_id" in form:
        set_handoff_chat_id(form.get("handoff_chat_id", ""))
    if "retrieval_threshold" in form and form.get("retrieval_threshold"):
        set_retrieval_threshold(form.get("retrieval_threshold", ""))
    if "institution_type" in form:
        set_institution_type(form.get("institution_type", ""))
    if "telegram_bot_token" in form:
        set_telegram_bot_token(form.get("telegram_bot_token", ""))
    if "timezone" in form and form.get("timezone"):
        set_timezone(form.get("timezone", ""))
    if any(
        k in form
        for k in (
            "whatsapp_account_sid",
            "whatsapp_auth_token",
            "whatsapp_from_number",
            "whatsapp_public_url",
        )
    ):
        set_whatsapp_settings(
            form.get("whatsapp_account_sid", ""),
            form.get("whatsapp_auth_token", ""),
            form.get("whatsapp_from_number", ""),
            form.get("whatsapp_public_url") if "whatsapp_public_url" in form else None,
        )
    if any(
        f"{day}_open" in form or f"{day}_close" in form or f"{day}_closed" in form
        for day in WEEKDAYS
    ):
        set_working_hours({k: v for k, v in form.items() if isinstance(v, str)})
    return RedirectResponse(
        "/dashboard?message=Settings+saved.", status_code=303
    )


@app.get("/appointments", response_class=HTMLResponse)
async def appointments_view(
    request: Request,
    status: str = "pending",
    message: str | None = None,
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    if not has_module("appointments"):
        return RedirectResponse(
            "/dashboard?error=Appointments+module+is+disabled+for+this+institution+type.",
            status_code=303,
        )
    items = appointments.list_all(status=None if status == "all" else status)
    return templates.TemplateResponse(
        request,
        "appointments.html",
        {
            "user": request.session.get("user"),
            "items": items,
            "status": status,
            "pending_count": appointments.pending_count(),
            "appointments_enabled": True,
            "open_handoffs": handoff.open_count(),
            "message": message,
        },
    )


@app.post("/appointments/{appointment_id}/{action}")
async def appointments_action(
    request: Request, appointment_id: int, action: str
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    status_map = {
        "confirm": "confirmed",
        "complete": "completed",
        "cancel": "cancelled",
        "reopen": "pending",
    }
    new_status = status_map.get(action)
    if not new_status:
        return RedirectResponse("/appointments?error=Unknown+action.", status_code=303)
    appointments.set_status(appointment_id, new_status)
    return RedirectResponse(
        f"/appointments?message=Appointment+%23{appointment_id}+marked+{new_status}.",
        status_code=303,
    )


@app.get("/inbox", response_class=HTMLResponse)
async def inbox(
    request: Request,
    status: str = "open",
    message: str | None = None,
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    items = handoff.list_all(status=None if status == "all" else status)
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "user": request.session.get("user"),
            "items": items,
            "status": status,
            "open_count": handoff.open_count(),
            "open_handoffs": handoff.open_count(),
            "appointments_enabled": has_module("appointments"),
            "pending_appointments": appointments.pending_count(),
            "message": message,
        },
    )


@app.post("/inbox/{handoff_id}/resolve")
async def resolve_handoff(request: Request, handoff_id: int):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    handoff.mark_resolved(handoff_id)
    return RedirectResponse(
        f"/inbox?message=Handoff+%23{handoff_id}+marked+resolved.",
        status_code=303,
    )


# --- Test report (temporary QA tool) -------------------------------------

@app.get("/report", response_class=HTMLResponse)
async def report(request: Request):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    report_path = Path("data/test_report.json")
    data = None
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
    return templates.TemplateResponse(
        request, "report.html", {"user": request.session.get("user"), "data": data}
    )


# --- WhatsApp webhook (public, Twilio calls into it) ---------------------

class WidgetMessage(BaseModel):
    session_id: str
    text: str


@app.get("/widget.js")
async def widget_js():
    """Embeddable JavaScript that injects the floating chat button.

    WIDGET_API_KEY is substituted in here rather than shipped in the static file.
    It is not a secret — anything the browser sends is readable in devtools — it
    just stops other sites casually embedding this widget against our API budget.
    The controls that actually bound spend are the per-IP rate limit and the
    global daily breaker in src/guards.py.
    """
    source = (STATIC_DIR / "widget.js").read_text(encoding="utf-8")
    source = source.replace("__WIDGET_API_KEY__", WIDGET_API_KEY or "")
    return Response(
        source,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/widget/demo", response_class=HTMLResponse)
async def widget_demo():
    """A sample 'organization website' page with the widget embedded, so
    we can demo the experience without putting it on a real customer site."""
    return FileResponse(STATIC_DIR / "widget-demo.html", media_type="text/html")


@app.get("/widget/config")
async def widget_config():
    """Public configuration the widget needs at load time.

    The name is frozen in llm.BOT_NAME rather than read from portal settings —
    it is baked into the cached system prefix, so a rename would invalidate the
    prompt cache for every visitor. Suggestions are fixed to the questions the
    knowledge base actually answers well.
    """
    return JSONResponse(
        {
            "bot_name": BOT_NAME,
            "greeting": (
                f"I am {BOT_NAME}. Ask me anything about what we build, what it "
                "costs, or how long it takes — I answer from our published "
                "prices and FAQ."
            ),
            "suggestions": [
                "What does a website cost?",
                "How long does it take?",
                "Do I own everything?",
                "Can I pay in parts?",
            ],
            "whatsapp": handoff_link.whatsapp_url(),
        }
    )


@app.post("/widget/chat")
async def widget_chat(request: Request, payload: WidgetMessage):
    """One message from a website visitor.

    Ordered so the cheap rejections happen first and never reach the paid API:
    auth -> shape -> local pre-filter -> per-IP rate limit -> global daily
    breaker -> DeepSeek. See src/guards.py.
    """
    if WIDGET_API_KEY:
        provided = request.headers.get("X-API-Key") or ""
        if not hmac.compare_digest(provided, WIDGET_API_KEY):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

    text = (payload.text or "").strip()
    session_id = (payload.session_id or "").strip()
    if not session_id or not text:
        return JSONResponse({"reply": "Please send a non-empty message."}, status_code=400)

    # Free: greetings, thanks, junk and over-length never cost an API call.
    canned = guards.reject_locally(text)
    if canned:
        return JSONResponse({"reply": canned, "followups": []})

    client_ip = (request.client.host if request.client else "") or "unknown"
    if not guards.rate_limiter.allow(client_ip):
        return JSONResponse(
            {
                "reply": "You have sent a lot of messages in a short time. Give it a "
                "moment, or reach a person on WhatsApp.",
                "whatsapp": handoff_link.whatsapp_url(text),
                "followups": [],
            },
            status_code=429,
        )

    # Global ceiling. Per-IP limits do not bound total spend when a caller rotates
    # addresses; this does. The widget stays useful when it trips — it shows
    # published content and the human handoff.
    if guards.breaker.is_open():
        log.warning("daily API cap reached (%s calls) — serving offline card", guards.breaker.used)
        return JSONResponse(handoff_link.offline_card(text))

    # Prefix so widget sessions cannot collide with anything else in the
    # shared conversation_memory table.
    full_session_id = f"web:{session_id[:64]}"

    guards.breaker.record()
    try:
        result = await chat.answer_message(full_session_id, text)
    except Exception:
        log.exception("widget_chat failed")
        return JSONResponse(handoff_link.offline_card(text))

    from src.memory import remember_message

    if result.is_security:
        reply_text = chat.build_security_reply()
        remember_message(full_session_id, "assistant", reply_text)
        return JSONResponse({"reply": reply_text, "followups": []})

    if result.is_off_topic:
        reply_text = chat.build_off_topic_reply()
        remember_message(full_session_id, "assistant", reply_text)
        return JSONResponse({"reply": reply_text, "followups": []})

    if result.is_handoff:
        handoff.record(
            question=text,
            user_chat_id=0,
            user_username=None,
            user_full_name=f"Web visitor ({session_id[:8]})",
        )
        reply_text = result.text or handoff_link.HANDOFF_MESSAGE
        remember_message(full_session_id, "assistant", reply_text)
        return JSONResponse(
            {
                "reply": reply_text,
                "whatsapp": handoff_link.whatsapp_url(text),
                "followups": [],
            }
        )

    return JSONResponse({"reply": result.text, "followups": []})


