"""Auth helpers, CSRF protection and tenant scoping."""
import hmac
import secrets
import time
from functools import wraps
from flask import session, g, request, redirect, url_for, abort, flash
from .db import get_db


def current_user():
    if "user" in g:
        return g.user
    uid = session.get("uid")
    g.user = None
    g.company = None
    if uid:
        row = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if row:
            g.user = dict(row)
            c = get_db().execute("SELECT * FROM companies WHERE id=?", (row["company_id"],)).fetchone()
            g.company = dict(c) if c else None
    return g.user


def current_company():
    current_user()
    return g.company


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not current_user():
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def roles_required(*roles):
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            u = current_user()
            if not u:
                return redirect(url_for("auth.login"))
            if u["role"] not in roles:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def check_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Invalid or missing CSRF token")


def get_owned(table: str, row_id, company_id: int):
    """Fetch a row only if it belongs to the tenant. Returns None otherwise (-> 404)."""
    allowed = {"services", "customers", "enquiries", "quotes", "quote_items"}
    if table not in allowed:
        raise ValueError("table not allowed")
    row = get_db().execute(
        f"SELECT * FROM {table} WHERE id=? AND company_id=?", (row_id, company_id)
    ).fetchone()
    return dict(row) if row else None


_HITS = {}


def over_limit(kind: str, key: str, limit: int, window: int) -> bool:
    """True when `key` already has `limit` recorded hits inside the last `window` seconds."""
    now = time.time()
    hits = [x for x in _HITS.get((kind, key), []) if now - x < window]
    _HITS[(kind, key)] = hits
    return len(hits) >= limit


def record_hit(kind: str, key: str):
    _HITS.setdefault((kind, key), []).append(time.time())
    if len(_HITS) > 5000:
        _HITS.clear()


def rate_limited(kind: str, limit: int, window: int = 60, key=None) -> bool:
    """Tiny in-memory limiter (one process), per client IP unless `key` is given. Counts the call; True = over the limit."""
    k = key or (request.remote_addr or "")
    if over_limit(kind, k, limit, window):
        return True
    record_hit(kind, k)
    return False
