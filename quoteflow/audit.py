"""Audit log of edits and approvals. Append-only from the app's point of view."""
import json
from .db import get_db


def log(company_id: int, user_id, entity: str, entity_id, action: str, detail=None):
    if detail is None:
        detail = ""
    elif not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    get_db().execute(
        "INSERT INTO audit_log (company_id, user_id, entity, entity_id, action, detail) VALUES (?,?,?,?,?,?)",
        (company_id, user_id, entity, entity_id, action, detail[:2000]),
    )
