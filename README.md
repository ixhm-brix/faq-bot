# FAQ Bot

A multi-channel AI assistant that answers questions from your organization's documents — on Telegram, WhatsApp, and an embeddable website widget — with an admin portal and human handoff.

## What it is

Drop your FAQ PDFs into the admin portal and the bot answers users' questions from them on **Telegram, WhatsApp, or a chat widget on your website** — all three share one answer pipeline, so a document you upload once is answered everywhere. When it doesn't know the answer, it forwards the question to a staff Telegram chat and logs it to an inbox for follow-up. The product is **vertical-agnostic** — it works for any organization that has FAQ documents: schools, hospitals, clinics, event organizers, government offices, NGOs, religious institutions, customer-service desks, anywhere a receptionist is currently re-answering the same questions all day. Orgs that schedule visits (clinics, salons, mechanics, consultants) can also switch on an **appointment-booking** flow.

## Architecture

```
   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
   │ Telegram     │   │ WhatsApp     │   │ Website widget   │
   │ (aiogram)    │   │ (Twilio)     │   │ (/widget.js)     │
   └──────┬───────┘   └──────┬───────┘   └────────┬─────────┘
          │                  │                    │
          └──────────────────┼────────────────────┘
                             ▼
        ┌────────────────────────────────────┐
        │  Shared chat core  (src/chat.py)   │
        │  - RAG retrieval + confidence band  │
        │  - 12-hour conversation memory      │
        │  - handoff / off-topic / security   │
        └─────┬──────────────────────┬─────────┘
              │                      │
              ▼                      ▼
   ┌──────────────────┐   ┌─────────────────────┐
   │  DeepSeek API     │   │  ChromaDB           │
   │  (chat answer)    │   │  (vector retrieval) │
   └──────────────────┘   └─────────┬───────────┘
                                    │
                ┌───────────────────┴────────────────┐
                │                                    │
                ▼                                    ▼
   ┌────────────────────────┐         ┌────────────────────────┐
   │  FastAPI admin portal   │         │  data/                  │
   │  (src/portal/)          │ ──────► │  - chroma/              │
   │  - upload/delete PDFs   │         │  - handoffs.db          │
   │  - tune settings        │         │  - appointments.db      │
   │  - handoff inbox        │         │  - conversation_memory  │
   │  - appointments         │         │  - users.db             │
   │  - WhatsApp webhook      │         │  - settings.json        │
   └────────────────────────┘         └────────────────────────┘
```

Every channel funnels into the shared chat core in [`src/chat.py`](src/chat.py), so the RAG + memory logic is identical everywhere. The bot and portal share the same `data/` directory, so a PDF uploaded in the portal is immediately queryable by the bot, and a setting changed in the portal takes effect on the next message without a restart.

## Features

- **Three channels, one brain**: a Telegram bot (aiogram), a WhatsApp channel (via Twilio), and an embeddable website chat widget, all sharing the same RAG pipeline in [`src/chat.py`](src/chat.py).
- **Voice notes**: send the Telegram bot a voice message and it transcribes it locally with Whisper (`faster-whisper`), then answers as if you'd typed it. Multilingual and runs on CPU or GPU — no audio API.
- **RAG over your PDFs powered by DeepSeek**, with **local embeddings** (sentence-transformers `all-MiniLM-L6-v2`) — runs on CPU, no embedding API key needed.
- **Confidence-calibrated grounding**: retrieval is scored high/medium/low/none and the answer is tuned to that — the bot answers confidently on strong matches and hands off rather than guessing on weak ones.
- **Smart decline routing**: the model classifies each turn so real-but-unknown questions are handed off to staff, off-topic questions are politely declined *without* paging anyone, and prompt-injection/jailbreak attempts are refused.
- **Appointment booking** (optional module): a guided Telegram flow (name → phone → reason → time) for orgs that schedule visits, validated against configurable working hours and timezone. Unlocked by the institution type in the portal.
- **Admin web portal**: upload/delete PDFs, set the assistant's name, tune retrieval strictness, edit suggestion buttons, configure WhatsApp, manage the handoff inbox and appointments. Multi-user login with bcrypt-hashed passwords and a signup flow.
- **AI-generated `/start` suggestions**: tap-to-ask buttons regenerated from your documents (so they fit your organization).
- **Follow-up question buttons** after each grounded answer — the bot suggests likely next questions based on the same chunks it just used.
- **12-hour conversation memory**: the bot remembers the chat and resolves follow-ups like *"what about Saturday?"* using prior context.
- **Human handoff**: questions the bot can't answer are logged in a portal inbox and forwarded to a configurable staff Telegram chat.
- **Continuous typing indicator** while the LLM is working — no awkward silent pauses.

## Quick start (local)

Requirements:

- Python 3.12
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A DeepSeek API key from <https://platform.deepseek.com>

Steps:

```bash
git clone https://github.com/ixhm-brix/faq-bot.git
cd faq-bot

python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# open .env and fill in TELEGRAM_BOT_TOKEN, DEEPSEEK_API_KEY,
# and a PORTAL_ADMIN_PASSWORD of your choice
```

Run the bot and the portal in **two separate terminals** (both from the project root, with the venv activated):

```bash
# terminal 1 — Telegram bot
python -m src.bot.main
```

```bash
# terminal 2 — admin portal
python -m uvicorn src.portal.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>, sign in with your admin username/password, upload a PDF, click **Regenerate from docs** under "Sample questions", then go to your bot on Telegram and send `/start`.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | From `@BotFather` — identifies your bot to the Telegram API. |
| `DEEPSEEK_API_KEY` | yes | DeepSeek chat-completions API key — used for answers and suggestion generation. |
| `PORTAL_ADMIN_USERNAME` | no (default `admin`) | Username for the admin portal login. |
| `PORTAL_ADMIN_PASSWORD` | yes | Password for the admin portal login. Must be set or the portal refuses to start. |
| `PORTAL_SESSION_SECRET` | no (auto-generated) | Cookie-signing secret for portal sessions. If unset, a random one is generated each startup (sessions don't survive restarts in dev). |

## Project layout

```
.
├── src/
│   ├── chat.py           # channel-neutral chat core (RAG + memory + routing)
│   ├── bot/              # aiogram Telegram bot
│   │   ├── main.py       # handlers, typing indicator, follow-up buttons
│   │   ├── booking.py    # appointment-booking FSM (optional module)
│   │   └── format.py     # markdown → Telegram HTML conversion
│   ├── portal/           # FastAPI admin portal
│   │   ├── main.py       # routes (portal, WhatsApp webhook, widget)
│   │   ├── templates/    # Jinja2 + Tailwind CDN
│   │   └── static/       # embeddable widget.js + demo page
│   ├── rag/              # retrieval pipeline
│   │   ├── ingest.py     # PDF → chunks → embeddings → ChromaDB
│   │   ├── retrieve.py   # query → top-k chunks + confidence band
│   │   └── store.py      # ChromaDB + embedding model
│   ├── whatsapp.py       # Twilio WhatsApp adapter + signature validation
│   ├── auth.py           # portal users (bcrypt, SQLite)
│   ├── appointments.py   # appointments store (SQLite)
│   ├── handoff.py        # handoff inbox (SQLite)
│   ├── llm.py            # DeepSeek wrapper + system prompts
│   ├── memory.py         # 12-hour conversation memory (SQLite)
│   ├── settings.py       # JSON-backed admin settings
│   └── config.py         # .env loading
├── scripts/              # dev / test helpers (sample-PDF generator, smoke tests)
├── docs/architecture.md  # RAG pipeline diagram + write-up
├── data/                 # generated at runtime, gitignored
│   ├── pdfs/             # uploaded PDFs
│   ├── chroma/           # ChromaDB persistent client
│   ├── handoffs.db       # handoff inbox
│   ├── appointments.db   # bookings
│   ├── users.db          # portal logins
│   ├── conversation_memory.sqlite3
│   └── settings.json     # portal-configurable settings
├── requirements.txt
├── .env.example
└── README.md
```

## Tech stack

- **Language**: Python 3.12
- **Bot framework**: aiogram 3.x (Telegram)
- **Web framework**: FastAPI + Jinja2 + Tailwind CSS (CDN)
- **WhatsApp**: Twilio REST API over `httpx`, with request-signature validation
- **LLM**: DeepSeek (OpenAI-compatible chat completions)
- **Embeddings**: sentence-transformers (`all-MiniLM-L6-v2`, 384-d, CPU)
- **Voice**: faster-whisper (CTranslate2, local; CPU or GPU)
- **Vector store**: ChromaDB (local, SQLite-backed)
- **PDF parsing**: pypdf
- **Booking**: dateparser (natural-language slots); **auth**: bcrypt

## Roadmap

Shipped since the first cut: the **WhatsApp channel**, the **website widget**, the **appointment-booking** vertical module, **multi-user portal auth**, and **voice notes** (Whisper transcription on Telegram). Still ahead:

- Voice notes on WhatsApp too (the transcription module is already channel-neutral), and replying with voice.
- More vertical modules on top of the institution-type switch — e.g. a results-lookup flow for schools, a ticket-lookup flow for events. The base product stays general-purpose; verticals are optional add-ons.
- OCR for scanned PDFs.
- Source-cited answers (*"from your Visit Policy, page 3"*).
- Analytics dashboard: top questions, handoff rate, response times.
- Per-org multi-tenancy (today a deployment serves one organization).

## License

TBD.
