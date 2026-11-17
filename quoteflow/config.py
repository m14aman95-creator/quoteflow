"""Configuration. Everything secret comes from environment variables."""
import os
import secrets

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTANCE_DIR = os.environ.get("QF_INSTANCE_DIR", os.path.join(BASE_DIR, "instance"))


def _load_secret_key() -> str:
    """Use SECRET_KEY from the environment. For local dev only, generate a random
    key once and keep it in the instance folder (never committed, never hardcoded)."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    path = os.path.join(INSTANCE_DIR, "dev_secret_key")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(key)
    os.chmod(path, 0o600)
    return key


class Config:
    SECRET_KEY = _load_secret_key()
    DATABASE = os.environ.get("QF_DATABASE", os.path.join(INSTANCE_DIR, "quoteflow.sqlite"))
    UPLOAD_DIR = os.path.join(INSTANCE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB request cap (logo upload, enquiry text)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("QF_SECURE_COOKIES", "0") == "1"
    # AI provider: "auto" (Claude if ANTHROPIC_API_KEY is set, else offline), "claude", "offline"
    AI_PROVIDER = os.environ.get("QF_AI_PROVIDER", "auto")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("QF_ANTHROPIC_MODEL", "claude-sonnet-5-5")
    # Outgoing email (any SMTP account). Leave SMTP_HOST empty to disable sending.
    # Values pasted into a host's settings page often carry stray or non-breaking spaces: clean them so mail never breaks sign-up.
    SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.environ["SMTP_PORT"].strip()) if os.environ.get("SMTP_PORT", "").strip().isdigit() else 587
    SMTP_USER = os.environ.get("SMTP_USER", "").strip()
    SMTP_PASSWORD = "".join(os.environ.get("SMTP_PASSWORD", "").split())      # app passwords never contain spaces
    SMTP_FROM = os.environ.get("SMTP_FROM", "").strip()      # sender address; defaults to SMTP_USER
    MAIL_FROM = os.environ.get("MAIL_FROM", "").strip()      # same, for the Brevo email API
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()   # HTTPS email API: works where SMTP ports are blocked (Render free)
    SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls")   # starttls | ssl | none
    MAX_ENQUIRY_CHARS = 4000
    DEFAULT_RETENTION_DAYS = 30
