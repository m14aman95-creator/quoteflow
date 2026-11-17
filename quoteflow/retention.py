"""Data minimisation: raw enquiry text is deleted after the company's retention period.
The structured extraction (names, quantities...) stays on the quote; the original message does not."""
from datetime import timedelta
from .timeutil import utcnow
from .db import get_db


def purge_date(retention_days: int) -> str:
    return (utcnow() + timedelta(days=int(retention_days))).strftime("%Y-%m-%d %H:%M:%S")


def purge_expired(company_id=None) -> int:
    db = get_db()
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    sql = "UPDATE enquiries SET raw_text=NULL WHERE raw_text IS NOT NULL AND purge_after IS NOT NULL AND purge_after < ?"
    args = [now]
    if company_id is not None:
        sql += " AND company_id=?"
        args.append(company_id)
    cur = db.execute(sql, args)
    db.commit()
    return cur.rowcount
