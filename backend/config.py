"""Runtime configuration. Everything can be overridden with environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SPENDFLOW_DATA") or os.environ.get("TALLY_DATA") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
# Reuse the original database so an upgrade never creates an empty ledger.
DB_PATH = DATA_DIR / ("tally.db" if (DATA_DIR / "tally.db").exists() else "spendflow.db")
FRONTEND_DIR = BASE_DIR / "frontend"

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_FILES_PER_IMPORT = 10
SESSION_DAYS = 30
CURRENCY = os.environ.get("SPENDFLOW_CURRENCY") or os.environ.get("TALLY_CURRENCY", "INR")
LOCALE = os.environ.get("SPENDFLOW_LOCALE") or os.environ.get("TALLY_LOCALE", "en-IN")

# Optional AI-assisted statement reading. Off unless a key is present, and even then
# it only runs when the user ticks the box on the upload dialog.
LLM_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("SPENDFLOW_LLM_MODEL") or os.environ.get("TALLY_LLM_MODEL", "claude-sonnet-5-5")

# Optional SMTP email delivery for password recovery (no email service until configured).
SMTP_HOST = os.environ.get("SPENDFLOW_SMTP_HOST", "").strip()
SMTP_USERNAME = os.environ.get("SPENDFLOW_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SPENDFLOW_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SPENDFLOW_SMTP_FROM", "").strip()
SMTP_MODE = os.environ.get("SPENDFLOW_SMTP_MODE", "starttls").strip().lower()
SMTP_PORT = int(os.environ.get("SPENDFLOW_SMTP_PORT", "465" if SMTP_MODE == "ssl" else "587"))

COOKIE_NAME = "spendflow_session"
LEGACY_COOKIE_NAME = "tally_session"
COOKIE_SECURE = os.environ.get("SPENDFLOW_COOKIE_SECURE") or os.environ.get("TALLY_COOKIE_SECURE", "0") == "1"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
