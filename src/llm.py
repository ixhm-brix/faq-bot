from openai import AsyncOpenAI

from src.config import DEEPSEEK_API_KEY
from src.memory import ChatMessage
from src.rag.retrieve import RetrievedChunk
from src.settings import get_bot_name

_client: AsyncOpenAI | None = None

NO_CONTEXT_MARKER = "NO_ANSWER_IN_DOCS"

_SYSTEM_PROMPT_TEMPLATE = """Your name is {bot_name}. You are an FAQ assistant for a specific organization. Be genuinely helpful and feel like a real assistant, not a search engine.

When the user asks who you are or what you are, introduce yourself as {bot_name}.

How to respond:

Conversation continuity rule: Treat each message as part of the same 12-hour chat. For normal follow-up questions, use the recent conversation to resolve references like "it", "that", "there", "one", "what about Saturday?", or "how do I book it?" Continue naturally from the previous topic instead of acting like the question arrived with no context.

1. Greetings or small talk ("hi", "hello", "how are you") → reply warmly and briefly invite a question.

2. Acknowledgments ("ok", "thanks", "got it") → reply briefly and politely (e.g. "Happy to help! Anything else?").

3. Conversation memory questions ("do you remember what I asked?", "what did I say?", "recap our conversation") → answer from the recent conversation. If there is no recent conversation, say you only remember this chat for 12 hours and do not have an earlier question yet.

4. Substantive questions → use the context below as your source of truth for organization-specific facts. You SHOULD:
   - Synthesize across multiple parts of the context to answer indirect or composite questions. For example, "what do I need to know before visiting campus?" can be answered by combining the address, parking/transport info, library hours, contact details, etc.
   - Use the recent conversation only to understand follow-up questions, references, and user preferences. Do not treat conversation history as a source of organization facts.
   - Group related facts into a clear, useful answer (bullets are great when there are several points).
   - Use a friendly, conversational tone. Don't lecture about your limitations.

   You must NOT:
   - Say you do not remember the conversation when recent conversation is provided.
   - Invent organization-specific facts not in the context (no made-up tuition figures, names, phone numbers, dates, or policies).
   - Refuse to answer just because the question isn't phrased exactly like an entry in the docs — combine what's there.

5. If the topic is genuinely not covered in the context at all (e.g. wifi password when the docs say nothing about wifi), reply with EXACTLY this token on its own line and nothing else: {marker}"""


def _system_prompt() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        bot_name=get_bot_name(),
        marker=NO_CONTEXT_MARKER,
    )


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY is not set in .env")
        _client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )
    return _client


def _format_history(history: list[ChatMessage]) -> str:
    if not history:
        return "(no recent conversation)"
    return "\n".join(
        f"{message.role}: {message.content}"
        for message in history
    )


def _build_user_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[ChatMessage] | None = None,
) -> str:
    if not chunks:
        context = "(no relevant documents found)"
    else:
        context = "\n\n---\n\n".join(c.text for c in chunks)

    recent_conversation = _format_history(history or [])
    return (
        f"Recent conversation from the last 12 hours:\n{recent_conversation}\n\n"
        f"Context:\n{context}\n\n"
        "Use the recent conversation to understand what the current question "
        "refers to, then answer using the context as the factual source.\n\n"
        f"Current user question: {question}"
    )


async def answer(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[ChatMessage] | None = None,
) -> str:
    response = await _get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": _build_user_prompt(question, chunks, history),
            },
        ],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


async def generate_followups(
    user_question: str,
    assistant_reply: str,
    chunks: list[RetrievedChunk],
    n: int = 3,
) -> list[str]:
    """Suggest 2-3 short follow-up questions a user might tap after this reply.

    Anchored on the chunks the answer used so suggestions are answerable.
    """
    if not chunks or not assistant_reply:
        return []
    context = "\n\n---\n\n".join(c.text for c in chunks[:4])
    prompt = (
        f"A user asked: {user_question}\n\n"
        f"You just answered:\n{assistant_reply}\n\n"
        f"Source documents available:\n{context}\n\n"
        f"Write {n} short, natural follow-up questions this user might tap as "
        f"buttons next. Each must:\n"
        f"- be a complete, self-contained question,\n"
        f"- be under 40 characters,\n"
        f"- be answerable from the source documents above,\n"
        f"- not repeat the question already asked.\n\n"
        f"Return only the questions, one per line, nothing else."
    )
    response = await _get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": "You write concise follow-up question suggestions.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )
    text = (response.choices[0].message.content or "").strip()
    asked_lower = user_question.lower().strip("?. ")
    candidates: list[str] = []
    for line in text.splitlines():
        cleaned = (
            line.strip()
            .lstrip("0123456789.)-*•· \t")
            .strip()
            .strip('"')
            .strip("'")
        )
        if 5 < len(cleaned) <= 50 and cleaned.lower().strip("?. ") != asked_lower:
            candidates.append(cleaned)
    return candidates[:n]


async def generate_sample_questions(
    chunks: list[RetrievedChunk], n: int = 4
) -> list[str]:
    """Generate short sample questions a typical user might ask, grounded in the docs.

    Used to populate the suggestion buttons on /start so they match the org's domain
    (university, hospital, event, etc.) rather than being hardcoded.
    """
    if not chunks:
        return []
    context = "\n\n---\n\n".join(c.text for c in chunks[:8])
    prompt = (
        f"Below are excerpts from one organization's FAQ documents.\n\n"
        f"{context}\n\n"
        f"Write exactly {n} short, natural questions a typical user might ask this "
        f"organization, based on what's in the documents. Each question must be:\n"
        f"- self-contained (no pronouns referring to other questions),\n"
        f"- under 50 characters,\n"
        f"- phrased as the user would type it (no quotes, no numbering).\n\n"
        f"Return only the questions, one per line, nothing else."
    )
    response = await _get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": "You write concise FAQ prompt suggestions.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
    )
    text = (response.choices[0].message.content or "").strip()
    candidates: list[str] = []
    for line in text.splitlines():
        cleaned = (
            line.strip()
            .lstrip("0123456789.)-*•· \t")
            .strip()
            .strip('"')
            .strip("'")
        )
        if 5 < len(cleaned) <= 64:
            candidates.append(cleaned)
    return candidates[:n]
