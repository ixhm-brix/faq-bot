"""WhatsApp channel adapter.

For the MVP we use Twilio because their sandbox lets you test end-to-end
without Meta Business verification (which takes days). The provider
abstraction is intentionally thin so we can add the Meta Cloud API
later without touching the chat core or other channel adapters.

Inbound: Twilio POSTs application/x-www-form-urlencoded to the webhook.
Outbound: POST to Twilio's Messages REST endpoint with Basic auth.

Memory session ID format: "wa:<E164-number>" — keeps WhatsApp users in
their own keyspace, separate from Telegram chat_ids and widget UUIDs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.settings import (
    get_whatsapp_account_sid,
    get_whatsapp_auth_token,
    get_whatsapp_from_number,
)

log = logging.getLogger("whatsapp")

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


@dataclass
class InboundMessage:
    from_number: str  # E164 like "+250788123456"
    profile_name: str  # WhatsApp display name (may be empty)
    text: str  # message body
    session_id: str  # "wa:+250788..." — pass to chat.answer_message


def parse_twilio_inbound(form: dict[str, Any]) -> InboundMessage | None:
    """Pull the bits we care about out of a Twilio webhook form payload.

    Returns None if the payload isn't a text message we can handle
    (e.g. media-only messages, status callbacks, weird shapes).
    """
    from_raw = str(form.get("From", "")).strip()
    body = str(form.get("Body", "")).strip()
    profile_name = str(form.get("ProfileName", "")).strip()
    if not from_raw or not body:
        return None
    # Twilio prefixes WhatsApp From with "whatsapp:"
    from_number = from_raw.removeprefix("whatsapp:").strip()
    if not from_number:
        return None
    return InboundMessage(
        from_number=from_number,
        profile_name=profile_name,
        text=body,
        session_id=f"wa:{from_number}",
    )


async def send_message(to_number: str, body: str) -> None:
    """Send a WhatsApp reply via Twilio. Raises RuntimeError if WhatsApp
    isn't configured yet — caller should check `whatsapp_configured()`."""
    sid = get_whatsapp_account_sid()
    token = get_whatsapp_auth_token()
    from_number = get_whatsapp_from_number()
    if not (sid and token and from_number):
        raise RuntimeError("WhatsApp credentials are not configured in the portal")

    to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
    url = f"{TWILIO_API_BASE}/Accounts/{sid}/Messages.json"
    payload = {"From": from_number, "To": to, "Body": body[:1600]}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, data=payload, auth=(sid, token))
    if resp.status_code >= 300:
        log.error(
            "Twilio send failed: %s %s — payload=%s",
            resp.status_code,
            resp.text[:500],
            {k: v for k, v in payload.items() if k != "Body"},
        )
        resp.raise_for_status()
