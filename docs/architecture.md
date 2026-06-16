# How the FAQ Bot Answers Questions

This is the RAG (Retrieval-Augmented Generation) pipeline behind the bot. There are
two flows: **ingestion** (runs once, when an admin uploads documents) and **live
query** (runs every time a user asks a question). They meet at the vector store —
ingestion writes to it, query reads from it.

```mermaid
flowchart LR
    subgraph INGEST["① INGESTION — runs once, when an admin uploads documents"]
        direction LR
        A1["Admin uploads PDF<br/><i>FAQ docs via the web portal</i>"]
        A2["Extract text<br/><i>pull raw text from each page</i>"]
        A3["Split into chunks<br/><i>~400-character passages, kept whole</i>"]
        A4["Embedding engine<br/><i>turns each passage into a searchable<br/>vector — privately, no third-party AI</i>"]
        A1 --> A2 --> A3 --> A4
    end

    DB[("Knowledge base<br/>(vector database)<br/><i>your documents,<br/>searchable by meaning</i>")]
    A4 --> DB

    subgraph QUERY["② LIVE QUERY — runs every time a user asks a question"]
        direction LR
        C["Telegram · WhatsApp · Website chat<br/><i>User question</i>"]
        Q1["Shared chat core<br/><i>one pipeline for all channels</i>"]
        Q2["Add conversation memory<br/><i>last 12h · resolves follow-ups<br/>like 'what about Saturday?'</i>"]
        Q3["Understand the question<br/><i>same engine · turns it into a<br/>searchable vector</i>"]
        Q4["Build prompt<br/><i>question + retrieved chunks + history</i>"]
        Q5["DeepSeek LLM<br/><i>answers using only the retrieved facts</i>"]
        D{"Can it<br/>answer?"}
        C --> Q1 --> Q2 --> Q3
        Q4 --> Q5 --> D
    end

    Q3 -- "embed, then search" --> DB
    DB -- "top matching chunks" --> Q4

    D -- "Answer found in docs" --> R1["✅ Reply to the user"]
    D -- "Real question, not in docs" --> R2["📨 Hand off to staff inbox"]
    D -- "Off-topic" --> R3["✋ Politely decline"]

    classDef green fill:#dcfce7,stroke:#16a34a,color:#14532d;
    classDef orange fill:#ffedd5,stroke:#ea580c,color:#7c2d12;
    classDef grey fill:#f3f4f6,stroke:#9ca3af,color:#374151;
    class R1 green;
    class R2 orange;
    class R3 grey;
```

## The two flows in words

**Ingestion (one-time per document):**
1. Admin uploads a PDF through the portal.
2. Text is extracted from each page (`pypdf`).
3. Text is split into ~400-character chunks, kept on line boundaries so Q&A pairs stay intact.
4. Each chunk is converted into a searchable vector by a built-in embedding engine that runs **inside the product's own environment** — the documents are never sent to an outside AI service for this step. (Technically: `sentence-transformers/all-MiniLM-L6-v2`.)
5. The chunks + vectors are stored in the product's own knowledge base (vector database, ChromaDB).

**Live query (every user message):**
1. The question arrives from any channel — Telegram, WhatsApp, or the website widget.
2. All channels funnel into one shared chat core, so the logic below is identical everywhere.
3. Recent conversation (last 12 hours) is added so follow-ups like "what about Saturday?" resolve against the earlier topic.
4. The question is embedded with the same model used at ingestion.
5. ChromaDB returns the most similar chunks (filtered by a configurable relevance threshold).
6. A prompt is built from the question + retrieved chunks + chat history.
7. DeepSeek writes an answer grounded only in the retrieved facts.
8. The result is routed three ways:
   - **Answer found** → reply to the user.
   - **Real question but not in the docs** → log to the staff handoff inbox (and notify staff on Telegram).
   - **Off-topic** (e.g. "what's the HTML tag for an image?") → politely decline, without bothering staff.

---

## Image-generator prompt (for a polished illustrated version)

The diagram above is the source of truth and lives in the repo. For a marketing/slide
illustration, paste the prompt below into an image generator. It fixes the retrieval
ordering (embed → search ChromaDB → build prompt):

```
A clean, modern technical architecture diagram of an AI FAQ assistant, left-to-right
flow, flat vector style, soft drop shadows, rounded rectangles, professional
blue-and-teal palette on a light background, each labeled box with a small icon and a
one-line caption. Title: "How the FAQ Assistant Answers Questions".

TOP LANE "① SETUP — runs once, when an organization uploads its documents":
  Upload PDF (FAQ docs via the web portal) → Extract text → Split into short passages →
  Embedding engine (caption: "understands each passage privately — documents are never
  shared with an outside AI service") → a cylinder labeled "Secure knowledge base"
  holding colored dots in a grid.

BOTTOM LANE "② ANSWERING — every time a user asks a question":
  Telegram + WhatsApp + Website-chat icons merge into "User question" →
  Shared assistant core (caption: "one brain across every channel") →
  Conversation memory (caption: "remembers the last 12 hours, handles follow-ups") →
  Understand the question → then an arrow goes UP to the "Secure knowledge base"
  cylinder labeled "search for relevant passages" and a return arrow comes back DOWN
  labeled "best-matching passages" into → Assemble the answer context →
  AI language model (sparkle icon, caption: "writes the answer using only the
  organization's own information") → decision diamond "Can it answer?" with three
  branches: green "Reply to the user", orange "Hand off to a staff member", grey
  "Politely decline off-topic questions".

Emphasize the secure knowledge base cylinder as the shared link between the two lanes:
setup writes to it, answering reads from it. Convey privacy and trust. Keep all text
short and legible.
```
