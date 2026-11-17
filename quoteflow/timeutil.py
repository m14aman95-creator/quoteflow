from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC datetime (stored as text in SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
