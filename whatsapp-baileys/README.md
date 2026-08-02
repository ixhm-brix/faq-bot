# WhatsApp → RAG adapter (Baileys)

A minimal, standalone WhatsApp bot. It listens for incoming text messages,
forwards each to an existing RAG HTTP API, and sends the answer back to the
same chat. One file (`index.js`), no database, no web server.

It talks to the RAG service like this:

```
POST {RAG_URL}/widget/chat
Content-Type: application/json
X-API-Key: {RAG_API_KEY}

{ "session_id": "<sender WhatsApp JID>", "text": "<message text>" }
```

and reads the `reply` field from the JSON response (the `followups` array is
ignored).

## ⚠️ Use a throwaway number

Baileys is an **unofficial** WhatsApp client. Log in with a **throwaway
number** you don't mind losing — WhatsApp can ban numbers that use unofficial
clients. Do not use your personal or business number.

## Setup

Requires **Node.js 18+** (uses the built-in `fetch`).

```bash
cd whatsapp-baileys
npm install
cp .env.example .env
# edit .env: set RAG_URL and RAG_API_KEY (RAG_API_KEY must match the RAG
# service's WIDGET_API_KEY)
npm start
```

On first run it prints a **QR code** in the terminal. On the throwaway phone:
open WhatsApp → **Settings → Linked Devices → Link a Device** → scan the QR.

The session is saved to the `auth/` folder, so subsequent starts reconnect
without a new scan. To re-link a different number, stop the bot, delete `auth/`,
and start again.

## Runtime & dependencies

This bot has **no brain of its own** — it is a thin client of the RAG portal.
Every message is forwarded to `{RAG_URL}/widget/chat`; the portal does the
retrieval + generation and returns the answer. Consequences:

- If the portal is **down or unreachable**, the bot stays connected but every
  reply is the fallback ("couldn't reach my brain… try again"). The portal
  must be running for real answers.
- `RAG_API_KEY` here must match the portal's `WIDGET_API_KEY`. If it doesn't
  (or the portal has a key and the bot doesn't), the portal returns `401` and
  the user gets the fallback. Change one → update and restart the other.

On a VPS, run **both as managed, auto-restarting processes** — they have
independent lifecycles, so restarting one does not restart the other.

**This bot — pm2:**

```bash
cd whatsapp-baileys
pm2 start index.js --name whatsapp-rag
pm2 save        # persist the process list across reboots
```

**The RAG portal — its own service** (systemd unit or pm2). With pm2, from the
RAG project root using its virtualenv:

```bash
pm2 start .venv/bin/python --name rag-portal -- \
  -m uvicorn src.portal.main:app --host 127.0.0.1 --port 8000
pm2 save
```

The bot reconnects automatically on dropped connections, and only stops trying
if WhatsApp reports the device was logged out (in which case delete `auth/` and
re-scan).

## Notes

- Only plain text is handled; images, audio, stickers, and reactions are
  ignored. Messages you send yourself (`fromMe`) are ignored.
- It replies in **any** chat it receives text in, including groups. To restrict
  it (e.g. direct chats only), filter on the sender JID in `index.js`.
- If the RAG call fails or times out (20s), the user gets a short
  "try again" message and the bot keeps running.
