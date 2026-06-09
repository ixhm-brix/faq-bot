"""Fire a Twilio-shaped webhook payload at the local /whatsapp/webhook so
we can sanity-check the parser + chat-core wiring without actually
having Twilio credentials configured.

Run: .\.venv\Scripts\python.exe scripts\test_whatsapp_webhook.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx


PORT = 8000
URL = f"http://127.0.0.1:{PORT}/whatsapp/webhook"

CASES = [
    ("On-topic", "What are your opening hours?"),
    ("Off-topic", "What is the html tag for an image?"),
    ("Handoff-worthy", "Do you have wheelchair access?"),
]


def main() -> None:
    for label, body in CASES:
        payload = {
            "From": "whatsapp:+250788123456",
            "To": "whatsapp:+14155238886",
            "Body": body,
            "ProfileName": "Smoke Test User",
            "WaId": "250788123456",
            "MessageSid": f"SM{label.replace(' ', '')}",
        }
        print(f"\n=== {label} ===")
        print(f"User: {body}")
        try:
            r = httpx.post(URL, data=payload, timeout=60.0)
            print(f"HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"ERROR: {e}")
            return
        print(
            "(no outbound WhatsApp message was actually sent — those go to "
            "Twilio only when whatsapp_configured() is True)"
        )


if __name__ == "__main__":
    main()
