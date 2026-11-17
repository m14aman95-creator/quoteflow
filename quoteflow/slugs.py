"""Small helpers: business portal slugs and phone normalisation."""
import re

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
RESERVED = {"admin", "api", "static", "login", "logout", "register", "settings", "quotes", "q", "c", "lang", "sw", "account",
            "enquiries", "requests", "catalogue", "customers", "audit", "onboarding", "dashboard"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:30].strip("-")
    return s if len(s) >= 3 else "business"


def slug_ok(slug: str) -> bool:
    return bool(SLUG_RE.match(slug or "")) and "--" not in slug and slug not in RESERVED


def ensure_slug(db, company_id: int) -> str:
    """Return the company's portal slug, creating a unique one from its name if it has none yet."""
    row = db.execute("SELECT slug, name_en, id FROM companies WHERE id=?", (company_id,)).fetchone()
    if not row:
        return ""
    if row["slug"]:
        return row["slug"]
    base = slugify(row["name_en"])
    if base in RESERVED:
        base += "-co"
    cand, n = base, 1
    while db.execute("SELECT 1 FROM companies WHERE lower(slug)=? AND id<>?", (cand, company_id)).fetchone():
        n += 1
        cand = f"{base}-{n}"
    db.execute("UPDATE companies SET slug=? WHERE id=?", (cand, company_id))
    return cand


def norm_phone(raw: str) -> str:
    """Digits only; a local 8-digit Bahrain number gets the 973 country code. '' when it is too short to be a phone."""
    d = "".join(ch for ch in (raw or "") if ch.isdigit())
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 8:
        d = "973" + d
    return d if 8 <= len(d) <= 15 else ""
