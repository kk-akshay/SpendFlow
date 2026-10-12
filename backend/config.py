"""Runtime configuration. Everything can be overridden with environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TALLY_DATA", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "tally.db"
FRONTEND_DIR = BASE_DIR / "frontend"

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_FILES_PER_IMPORT = 10
SESSION_DAYS = 30
CURRENCY = os.environ.get("TALLY_CURRENCY", "INR")
LOCALE = os.environ.get("TALLY_LOCALE", "en-IN")

# Optional AI-assisted statement reading. Off unless a key is present, and even then
# it only runs when the user ticks the box on the upload dialog.
LLM_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("TALLY_LLM_MODEL", "claude-sonnet-5-5")

COOKIE_NAME = "tally_session"
COOKIE_SECURE = os.environ.get("TALLY_COOKIE_SECURE", "0") == "1"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
