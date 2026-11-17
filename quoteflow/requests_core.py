"""Customer service requests: statuses, the timeline, notifications, and the hooks the quote flow calls.

A request is created by a customer in the portal. The owner turns it into a quotation the normal way (review, price,
approve). Statuses move forward from three sources: the customer (cancel, accept, decline), the quote flow (reviewing,
quoted) and the owner (scheduled, in progress, completed, cancelled)."""
import secrets
from flask import current_app, url_for
from . import audit, mailer, verify
from .timeutil import utcnow
from .slugs import ensure_slug

STATUSES = ["new", "reviewing", "quoted", "accepted", "scheduled", "in_progress", "completed", "declined", "cancelled"]
OWNER_SETTABLE = ["reviewing", "scheduled", "in_progress", "completed", "cancelled"]
CUSTOMER_CANCELLABLE = {"new", "reviewing", "quoted"}
STEPS = ["new", "reviewing", "quoted", "accepted", "scheduled", "in_progress", "completed"]   # the progress bar
CLOSED = {"completed", "declined", "cancelled"}
LABEL_EN = {"new": "Received", "reviewing": "Under review", "quoted": "Quotation ready", "accepted": "Accepted",
            "scheduled": "Scheduled", "in_progress": "In progress", "completed": "Completed",
            "declined": "Quotation declined", "cancelled": "Cancelled"}


def next_ref(db, company_id: int) -> str:
    db.execute("UPDATE companies SET request_seq = request_seq + 1 WHERE id=?", (company_id,))
    seq = db.execute("SELECT request_seq FROM companies WHERE id=?", (company_id,)).fetchone()["request_seq"]
    return f"R-{utcnow().year}-{seq:04d}"


def add_event(db, company_id, request_id, actor, kind="status", status="", message=""):
    db.execute("INSERT INTO request_events (company_id, request_id, actor, kind, status, message) VALUES (?,?,?,?,?,?)",
               (company_id, request_id, actor, kind, status, (message or "").strip()[:1000]))


def set_status(db, req, status, actor, message="", scheduled_for=None, owner_seen=None):
    """Move a request to a new status, record it on the timeline and return the updated row."""
    assert status in STATUSES
    db.execute("""UPDATE service_requests SET status=?, scheduled_for=COALESCE(?, scheduled_for),
                  owner_seen=COALESCE(?, owner_seen), updated_at=datetime('now') WHERE id=? AND company_id=?""",
               (status, scheduled_for, owner_seen, req["id"], req["company_id"]))
    add_event(db, req["company_id"], req["id"], actor, "status", status, message)
    audit.log(req["company_id"], None, "request", req["id"], f"status_{status}", {"by": actor})
    return db.execute("SELECT * FROM service_requests WHERE id=?", (req["id"],)).fetchone()


def portal_url(slug: str, path: str = "") -> str:
    base = url_for("portal.home", slug=slug, _external=True)
    return base + path


def notify_customer(company, customer, subject_en, subject_ar, body_en, body_ar):
    """Email the customer if they gave an address and email is set up. Never raises."""
    if not customer or not (customer["email"] or "").strip():
        return False
    if verify.active(company) and not customer["email_verified_at"]:
        return False                      # only confirmed addresses get updates
    name = company["name_en"] or company["name_ar"]
    body = f"{body_en}\n\n— {name}\n\n──────────\n\n{body_ar}\n\n— {company['name_ar'] or name}"
    return mailer.send_notice(current_app.config, to=customer["email"].strip(),
                              subject=f"{subject_en} / {subject_ar}", body=body)


def notify_owner(company, subject, body):
    if company["email"] and not company["email"].endswith("@local.invalid"):
        return mailer.send_notice(current_app.config, to=company["email"], subject=subject, body=body)
    return False


# ---------------------------------------------------------------- hooks called by the quote flow
def _by_quote(db, company_id, quote_id):
    return db.execute("SELECT * FROM service_requests WHERE quote_id=? AND company_id=?", (quote_id, company_id)).fetchone()


def on_quote_created(db, company_id, enquiry_id, quote_id):
    req = db.execute("SELECT * FROM service_requests WHERE enquiry_id=? AND company_id=?", (enquiry_id, company_id)).fetchone()
    if not req:
        return
    db.execute("UPDATE service_requests SET quote_id=? WHERE id=?", (quote_id, req["id"]))
    if req["status"] == "new":
        set_status(db, req, "reviewing", "system", owner_seen=1)


def on_quote_approved(db, company, quote_id):
    """The owner approved the quotation: publish it to the customer's portal (link + status) and tell them."""
    req = _by_quote(db, company["id"], quote_id)
    if not req:
        return
    q = db.execute("SELECT share_token, number FROM quotes WHERE id=? AND company_id=?", (quote_id, company["id"])).fetchone()
    if not q["share_token"]:
        db.execute("UPDATE quotes SET share_token=? WHERE id=? AND company_id=?",
                   (secrets.token_urlsafe(24), quote_id, company["id"]))
    if req["status"] in ("new", "reviewing", "quoted"):
        req = set_status(db, req, "quoted", "system", owner_seen=1)
        cust = db.execute("SELECT * FROM customers WHERE id=?", (req["customer_id"],)).fetchone()
        link = portal_url(company["slug"] or ensure_slug(db, company["id"]), f"/r/{req['id']}")
        notify_customer(company, cust,
                        f"Your quotation for {req['ref']} is ready", f"عرض السعر للطلب {req['ref']} جاهز",
                        f"Your quotation {q['number']} is ready. Open it here, choose any add-ons and accept when ready:\n{link}",
                        f"عرض السعر {q['number']} جاهز. افتح الرابط التالي، واختر الإضافات إن أردت، ثم وافق عليه:\n{link}")


def on_quote_unlocked(db, company_id, quote_id):
    req = _by_quote(db, company_id, quote_id)
    if req and req["status"] == "quoted":
        set_status(db, req, "reviewing", "system", owner_seen=1)


def on_quote_response(db, company_id, quote_id, accepted: bool, actor="customer"):
    req = _by_quote(db, company_id, quote_id)
    if req and req["status"] in ("new", "reviewing", "quoted"):
        set_status(db, req, "accepted" if accepted else "declined", actor, owner_seen=0 if actor == "customer" else 1)
