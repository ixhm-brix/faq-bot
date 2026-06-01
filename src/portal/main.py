import logging
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.config import (
    PORTAL_ADMIN_PASSWORD,
    PORTAL_ADMIN_USERNAME,
    PORTAL_SESSION_SECRET,
)
from src import handoff
from src.llm import generate_sample_questions
from src.rag.ingest import ingest_pdf
from src.rag.retrieve import RetrievedChunk
from src.rag.store import get_collection
from src.settings import (
    get_bot_name,
    get_handoff_chat_id,
    get_retrieval_threshold,
    get_suggested_questions,
    set_bot_name,
    set_handoff_chat_id,
    set_retrieval_threshold,
    set_suggested_questions,
)

PDF_DIR = Path("data/pdfs")
TEMPLATES_DIR = Path(__file__).parent / "templates"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("portal")

if not PORTAL_ADMIN_PASSWORD:
    raise RuntimeError(
        "PORTAL_ADMIN_PASSWORD is not set. Set it in .env before starting the portal."
    )

app = FastAPI(title="FAQ Bot Portal")
app.add_middleware(SessionMiddleware, secret_key=PORTAL_SESSION_SECRET)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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
    target = "/dashboard" if is_authed(request) else "/login"
    return RedirectResponse(target, status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if is_authed(request):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"user": None, "error": None}
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == PORTAL_ADMIN_USERNAME and password == PORTAL_ADMIN_PASSWORD:
        request.session["user"] = username
        return RedirectResponse("/dashboard", status_code=303)
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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": request.session.get("user"),
            "documents": list_documents(),
            "bot_name": get_bot_name(),
            "handoff_chat_id": get_handoff_chat_id() or "",
            "retrieval_threshold": f"{get_retrieval_threshold():.2f}",
            "open_handoffs": handoff.open_count(),
            "suggestions": get_suggested_questions(),
            "message": message,
            "error": error,
        },
    )


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return RedirectResponse(
            "/dashboard?error=Only+PDF+files+are+supported.", status_code=303
        )

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / Path(file.filename).name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        n_chunks = ingest_pdf(target)
    except Exception as e:
        log.exception("Ingest failed for %s", target.name)
        return RedirectResponse(
            f"/dashboard?error=Failed+to+ingest+{target.name}:+{e}",
            status_code=303,
        )

    if n_chunks == 0:
        return RedirectResponse(
            f"/dashboard?error=No+text+extracted+from+{target.name}+(scanned+PDFs+need+OCR).",
            status_code=303,
        )

    return RedirectResponse(
        f"/dashboard?message=Ingested+{n_chunks}+chunks+from+{target.name}.",
        status_code=303,
    )


@app.post("/settings")
async def update_settings(
    request: Request,
    bot_name: str = Form(...),
    handoff_chat_id: str = Form(""),
    retrieval_threshold: str = Form(""),
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=303)
    set_bot_name(bot_name)
    set_handoff_chat_id(handoff_chat_id)
    if retrieval_threshold:
        set_retrieval_threshold(retrieval_threshold)
    return RedirectResponse(
        "/dashboard?message=Settings+saved.", status_code=303
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
