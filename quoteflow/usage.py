"""Monthly quotation usage counter. Limits are enforced; payments are not built."""
from datetime import datetime
from .timeutil import utcnow
from .db import get_db
from .plans import plan_limit


def month_key(now=None) -> str:
    return (now or utcnow()).strftime("%Y-%m")


def quotes_used(company_id: int) -> int:
    row = get_db().execute(
        "SELECT quotes_created FROM usage WHERE company_id=? AND month=?",
        (company_id, month_key()),
    ).fetchone()
    return row["quotes_created"] if row else 0


def usage_summary(company: dict) -> dict:
    used = quotes_used(company["id"])
    limit = plan_limit(company["plan"])
    return {"used": used, "limit": limit, "remaining": max(limit - used, 0),
            "pct": min(100, int(used * 100 / limit)) if limit else 100,
            "exceeded": used >= limit}


def can_create_quote(company: dict) -> bool:
    return not usage_summary(company)["exceeded"]


def record_quote_created(company_id: int):
    get_db().execute(
        """INSERT INTO usage (company_id, month, quotes_created) VALUES (?,?,1)
           ON CONFLICT(company_id, month) DO UPDATE SET quotes_created = quotes_created + 1""",
        (company_id, month_key()),
    )
