# FAQ Bot

A Telegram AI assistant that answers questions from your organization's documents, with an admin portal and human handoff.

## What it is

Drop your FAQ PDFs into the admin portal and the bot answers users' questions from them on Telegram. When it doesn't know the answer, it forwards the question to a staff Telegram chat and logs it to an inbox for follow-up. The product is **vertical-agnostic** — it works for any organization that has FAQ documents: schools, hospitals, clinics, event organizers, government offices, NGOs, religious institutions, customer-service desks, anywhere a receptionist is currently re-answering the same questions all day.

## Architecture

```
                ┌────────────────────────┐
                │  Telegram user          │
                └───────────┬─────────────┘
                            │
                            ▼
        ┌────────────────────────────────────┐
        │  aiogram bot  (src/bot/)            │
        │  - typing indicator                  │
        │  - suggestion / follow-up buttons    │
        │  - 12-hour conversation memory       │
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
   │  - tune settings        │         │  - conversation_memory  │
   │  - handoff inbox        │         │  - settings.json        │
   └────────────────────────┘         └────────────────────────┘
```

The bot and portal share the same `data/` directory, so a PDF uploaded in the portal is immediately queryable by the bot, and a setting changed in the portal takes effect on the next message without a restart.

## Features

- **Telegram bot powered by DeepSeek** with RAG over uploaded PDFs.
- **Local embeddings** (sentence-transformers `all-MiniLM-L6-v2`) — runs on CPU, no embedding API key needed.
- **Admin web portal**: upload/delete PDFs, set the assistant's name, tune retrieval strictness, edit suggestion buttons, view the handoff inbox.
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
│   ├── bot/              # aiogram Telegram bot
│   │   ├── main.py       # handlers, FSM, typing indicator, follow-up buttons
│   │   └── format.py     # markdown → Telegram HTML conversion
│   ├── portal/           # FastAPI admin portal
│   │   ├── main.py       # routes
│   │   └── templates/    # Jinja2 + Tailwind CDN
│   ├── rag/              # retrieval pipeline
│   │   ├── ingest.py     # PDF → chunks → embeddings → ChromaDB
│   │   ├── retrieve.py   # query → top-k chunks
│   │   └── store.py      # ChromaDB + embedding model
│   ├── llm.py            # DeepSeek wrapper + system prompts
│   ├── memory.py         # 12-hour conversation memory (SQLite)
│   ├── handoff.py        # handoff inbox (SQLite)
│   ├── settings.py       # JSON-backed admin settings
│   └── config.py         # .env loading
├── scripts/              # dev / test helpers (sample-PDF generator, smoke tests)
├── data/                 # generated at runtime, gitignored
│   ├── pdfs/             # uploaded PDFs
│   ├── chroma/           # ChromaDB persistent client
│   ├── handoffs.db       # handoff inbox
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
- **LLM**: DeepSeek (OpenAI-compatible chat completions)
- **Embeddings**: sentence-transformers (`all-MiniLM-L6-v2`, 384-d, CPU)
- **Vector store**: ChromaDB (local, SQLite-backed)
- **PDF parsing**: pypdf

## Roadmap

- WhatsApp channel (so patients/customers can reach the bot on the messenger they already use).
- Multilingual support and voice messages (Whisper transcription).
- A "what kind of institution are you?" question at portal setup that unlocks **vertical-specific optimizations** — for example, an appointment-booking flow for orgs that schedule visits (clinics, salons, mechanics, consultants), a results-lookup flow for schools, a ticket-lookup flow for events, etc. The base product stays general-purpose; verticals are optional add-ons.
- OCR for scanned PDFs.
- Source-cited answers (*"from your Visit Policy, page 3"*).
- Analytics dashboard: top questions, handoff rate, response times.

## License

TBD.
