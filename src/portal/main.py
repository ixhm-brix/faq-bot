import hmac
import json
import logging
import shutil
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from src.config import (
    PORTAL_ADMIN_PASSWORD,
    PORTAL_ADMIN_USERNAME,
    PORTAL_SESSION_SECRET,
    WIDGET_API_KEY,
)
from src import appointments, auth, chat, handoff, whatsapp
from src.llm import generate_followups, generate_sample_questions
from src.rag.ingest import ingest_pdf
from src.rag.retrieve import RetrievedChunk
from src.rag.store import get_collection
from src.settings import (
    INSTITUTION_TYPES,
    WEEKDAYS,
    get_bot_name,
    get_handoff_chat_id,
    get_institution_type,
    get_retrieval_threshold,
    get_suggested_questions,
    get_telegram_bot_token,
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


def list_documents() -> list[dict]:
    coll = get_collection()
    if coll.count() == 0:
        return []
    result = coll.get()
    counts: dict[str, int] = {}
    for meta in result["metadatas"]:
        src = meta.get("source", "?")
        counts[src] = counts.get(src, 0) + 1
    return sorted(
        ({"source": s, "chunks": c} for s, c in counts.items()),
        key=lambda d: d["source"],
    )


async def refresh_suggestions() -> list[str]:
    """Regenerate the bot's /start suggestion buttons based on current docs.

    Called automatically after upload/delete and manually via the portal button.
    Returns the new list of questions (may be empty if no docs or LLM failed).
    """
    coll = get_collection()
    if coll.count() == 0:
        set_suggested_questions([])
        return []
    sample = coll.get(limit=12)
    chunks: list[RetrievedChunk] = []
    for doc, meta in zip(sample["documents"], sample["metadatas"]):
        if not doc:
            continue
        chunks.append(
            RetrievedChunk(
                text=doc,
                source=(meta or {}).get("source", "?"),
                distance=0.0,
            )
        )
    try:
        questions = await generate_sample_questions(chunks)
    except Exception:
        log.exception("Failed to generate sample questions")
        return get_suggested_questions()
    set_suggested_questions(questions)
    return questions


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
            "documents": list_documents(),
            "bot_name": get_bot_name(),
            "telegram_bot_token": get_telegram_bot_token(),
            "whatsapp_account_sid": get_whatsapp_account_sid(),
            "whatsapp_from_number": get_whatsapp_from_number(),
            "whatsapp_public_url": get_whatsapp_public_url(),
            "whatsapp_configured": whatsapp_configured(),
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


@app.post("/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    ingested: list[str] = []      # "name (N chunks)"
    total_chunks = 0
    skipped: list[str] = []       # "name (reason)"

    for file in files:
        name = Path(file.filename or "").name
        if not name:
            continue  # empty file input slot — ignore
        if not name.lower().endswith(".pdf"):
            skipped.append(f"{name} (not a PDF)")
            continue
        target = PDF_DIR / name
        try:
            with target.open("wb") as f:
                shutil.copyfileobj(file.file, f)
            n_chunks = ingest_pdf(target)
        except Exception as e:
            log.exception("Ingest failed for %s", name)
            skipped.append(f"{name} ({e})")
            continue
        if n_chunks == 0:
            skipped.append(f"{name} (no text — scanned PDFs need OCR)")
            continue
        ingested.append(f"{name} ({n_chunks} chunks)")
        total_chunks += n_chunks

    params: dict[str, str] = {}
    if ingested:
        params["message"] = (
            f"Ingested {total_chunks} chunks from {len(ingested)} file"
            f"{'' if len(ingested) == 1 else 's'}: {', '.join(ingested)}."
        )
    if skipped:
        params["error"] = "Skipped " + "; ".join(skipped)
    if not params:
        params["error"] = "No files were uploaded."

    return RedirectResponse(f"/dashboard?{urlencode(params)}", status_code=303)


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

@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """Twilio WhatsApp webhook. Twilio sends application/x-www-form-urlencoded
    on every incoming message and expects a quick 200 — we reply
    asynchronously over the REST API rather than via TwiML so the bot can
    take its time."""
    form = await request.form()
    params = {k: v for k, v in form.items() if isinstance(v, str)}

    # Verify the request really came from Twilio before doing any work.
    # Twilio signs against the URL it was configured to call; behind a
    # tunnel/proxy that differs from what we see, so prefer the admin-set
    # public URL and fall back to the request's own URL.
    signed_url = get_whatsapp_public_url() or str(request.url)
    signature = request.headers.get("X-Twilio-Signature")
    if not whatsapp.validate_twilio_request(
        get_whatsapp_auth_token(), signed_url, params, signature
    ):
        log.warning("Rejected WhatsApp webhook with invalid/missing Twilio signature")
        return JSONResponse({"status": "forbidden"}, status_code=403)

    inbound = whatsapp.parse_twilio_inbound(params)
    if inbound is None:
        # Status callbacks, media-only, weird payloads — acknowledge and drop.
        return JSONResponse({"status": "ignored"})

    try:
        result = await chat.answer_message(inbound.session_id, inbound.text)
    except Exception:
        log.exception("WhatsApp chat.answer_message failed")
        try:
            await whatsapp.send_message(
                inbound.from_number,
                "Sorry, something went wrong on our side. Please try again in a moment.",
            )
        except Exception:
            log.exception("Failed to send WhatsApp error reply")
        return JSONResponse({"status": "error"}, status_code=200)

    from src.memory import remember_message

    if result.is_security:
        reply_text = chat.build_security_reply()
        remember_message(inbound.session_id, "assistant", reply_text)
    elif result.is_off_topic:
        reply_text = chat.build_off_topic_reply()
        remember_message(inbound.session_id, "assistant", reply_text)
    elif result.is_handoff:
        handoff.record(
            question=inbound.text,
            user_chat_id=0,
            user_username=None,
            user_full_name=f"WhatsApp: {inbound.profile_name or inbound.from_number}",
        )
        reply_text = result.text or (
            "I couldn't find that in our documents, so I've logged your question "
            "for our team to follow up."
        )
        remember_message(inbound.session_id, "assistant", reply_text)
    else:
        reply_text = result.text

    try:
        await whatsapp.send_message(inbound.from_number, reply_text)
    except RuntimeError as e:
        log.error("WhatsApp not configured: %s", e)
    except Exception:
        log.exception("Failed to send WhatsApp reply")

    return JSONResponse({"status": "ok"})


# --- Website widget (public, embeddable) ----------------------------------

class WidgetMessage(BaseModel):
    session_id: str
    text: str


@app.get("/widget.js")
async def widget_js():
    """Embeddable JavaScript that injects the floating chat button."""
    return FileResponse(
        STATIC_DIR / "widget.js",
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
    """Public configuration the widget needs at load time."""
    name = get_bot_name()
    return JSONResponse(
        {
            "bot_name": name,
            "greeting": f"Hi! I'm {name}. How can I help?",
            "suggestions": get_suggested_questions()[:6],
        }
    )


@app.post("/widget/chat")
async def widget_chat(request: Request, payload: WidgetMessage):
    """Process one message from a website visitor and return the bot's reply."""
    # Shared-secret guard. When WIDGET_API_KEY is configured, callers must
    # present it in X-API-Key; reject before doing any work otherwise. When
    # it's unset we allow through (a startup warning was already logged) so
    # local dev isn't broken.
    if WIDGET_API_KEY:
        provided = request.headers.get("X-API-Key") or ""
        if not hmac.compare_digest(provided, WIDGET_API_KEY):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

    text = (payload.text or "").strip()
    session_id = (payload.session_id or "").strip()
    if not session_id or not text:
        return JSONResponse(
            {"reply": "Please send a non-empty message."}, status_code=400
        )

    # Prefix the session id so it can't collide with Telegram chat_ids in
    # the shared conversation_memory table.
    full_session_id = f"web:{session_id[:64]}"

    try:
        result = await chat.answer_message(full_session_id, text)
    except Exception:
        log.exception("widget_chat failed")
        return JSONResponse(
            {"reply": "Sorry, something went wrong on our side. Please try again."}
        )

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
        reply_text = result.text or (
            "I couldn't find that in our documents, so I've logged your question "
            "for our team to follow up. If you'd like a quicker answer, please "
            "leave us your email or contact us directly."
        )
        remember_message(full_session_id, "assistant", reply_text)
        return JSONResponse({"reply": reply_text, "followups": []})

    # Grounded answer — offer the same follow-up suggestions the bot shows on
    # Telegram, generated from the chunks this answer used.
    try:
        followups = await generate_followups(text, result.text, result.chunks_used)
    except Exception:
        log.exception("widget followups failed")
        followups = []
    return JSONResponse({"reply": result.text, "followups": followups})


@app.post("/delete")
async def delete(request: Request, source: str = Form(...)):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)

    coll = get_collection()
    coll.delete(where={"source": source})

    pdf_file = PDF_DIR / source
    if pdf_file.exists():
        pdf_file.unlink()

    return RedirectResponse(
        f"/dashboard?message=Deleted+{source}.", status_code=303
    )


@app.post("/suggestions/refresh")
async def refresh_suggestions_route(request: Request):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    questions = await refresh_suggestions()
    if questions:
        msg = f"Regenerated+{len(questions)}+suggestions.+Edit+if+you+want+then+Save."
    else:
        msg = "Could+not+generate+suggestions+(no+docs+or+LLM+error)."
    return RedirectResponse(f"/dashboard?message={msg}", status_code=303)


@app.post("/suggestions")
async def save_suggestions(request: Request, suggestions: str = Form("")):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    items = [line.strip() for line in suggestions.splitlines() if line.strip()]
    set_suggested_questions(items[:6])
    return RedirectResponse(
        "/dashboard?message=Suggestions+saved.", status_code=303
    )
