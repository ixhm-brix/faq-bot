import html
import re


def md_to_html(text: str) -> str:
    """Convert a small subset of Markdown to Telegram-supported HTML.

    Telegram only supports a handful of HTML tags: <b>, <i>, <code>, <pre>,
    <a>, <s>, <u>. We map common LLM markdown to those and escape the rest.
    """
    text = html.escape(text)
    text = re.sub(r"```(.+?)```", lambda m: f"<pre>{m.group(1)}</pre>", text, flags=re.DOTALL)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    return text
