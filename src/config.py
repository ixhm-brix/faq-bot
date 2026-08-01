import os
import secrets

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Shared secret guarding the public POST /widget/chat endpoint. When set,
# callers must send it in the X-API-Key header. When unset, the endpoint is
# left open (with a startup warning) so local dev isn't broken.
WIDGET_API_KEY = os.getenv("WIDGET_API_KEY")

PORTAL_ADMIN_USERNAME = os.getenv("PORTAL_ADMIN_USERNAME", "admin")
PORTAL_ADMIN_PASSWORD = os.getenv("PORTAL_ADMIN_PASSWORD", "")
PORTAL_SESSION_SECRET = os.getenv("PORTAL_SESSION_SECRET") or secrets.token_urlsafe(32)
