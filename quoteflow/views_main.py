import io
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect, url_for, flash, session,
                   current_app, send_file, abort)
from .db import get_db
from . import audit
from .security import login_required, current_company, current_user, roles_required
from .usage import usage_summary
from .plans import PLANS

bp = Blueprint("main", __name__)


def _percent_to_bp(text: str, default=1000) -> int:
    try:
        v = Decimal((text or "").strip())
    except InvalidOperation:
        return default
    if v < 0 or v > 100:
        return default
    return int((v * 100).to_integral_value())


@bp.route("/lang/<code>")
def set_lang(code):
    if code in ("en", "ar"):
        session["ui_lang"] = code
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.route("/")
@login_required
def dashboard():
    from datetime import date
    from .views_quotes import effective_status, STATUSES
    c = current_company()
    db = get_db()
    recent = db.execute(
        """SELECT q.*, cu.name AS customer_name FROM quotes q
           LEFT JOIN customers cu ON cu.id=q.customer_id
           WHERE q.company_id=? ORDER BY q.id DESC LIMIT 5""", (c["id"],)).fetchall()
    n_services = db.execute("SELECT COUNT(*) n FROM services WHERE company_id=?", (c["id"],)).fetchone()["n"]

    allq = db.execute("SELECT status, valid_until, total_fils, created_at, approved_at FROM quotes WHERE company_id=?",
                      (c["id"],)).fetchall()
    counts = {k: 0 for k in STATUSES}
    value = {k: 0 for k in STATUSES}
    for q in allq:
        st = effective_status(q)
        counts[st] += 1
        value[st] += q["total_fils"] or 0
    decided = counts["accepted"] + counts["rejected"] + counts["expired"]
    win_rate = round(100 * counts["accepted"] / decided) if decided else None
    open_value = value["sent"] + value["follow_up"]

    # last 6 months of quoted value (approved quotes)
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(6):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    series = {k: 0 for k in months}
    for q in allq:
        if q["approved_at"] and q["created_at"]:
            key = (int(q["created_at"][:4]), int(q["created_at"][5:7]))
            if key in series:
                series[key] += q["total_fils"] or 0
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    top = max(series.values()) or 1
    bars = [{"label": names[k[1] - 1], "fils": series[k], "h": round(100 * series[k] / top)} for k in months]

    donut, offset = [], 25.0          # 25 = start at 12 o'clock
    total_n = sum(counts.values())
    for st in STATUSES:
        if counts[st]:
            pct = 100.0 * counts[st] / total_n
            donut.append({"status": st, "n": counts[st], "pct": round(pct, 2), "offset": round(offset, 2)})
            offset -= pct
    return render_template("dashboard.html", usage=usage_summary(c), recent=recent, n_services=n_services, plans=PLANS,
                           counts=counts, total_n=total_n, win_rate=win_rate, open_value=open_value,
                           accepted_value=value["accepted"], bars=bars, donut=donut,
                           STATUS_LABEL={"draft": "Draft", "sent": "Sent", "follow_up": "Follow-up", "accepted": "Accepted",
                                         "rejected": "Rejected", "expired": "Expired"}, STATUSES=STATUSES)


@bp.route("/onboarding")
@login_required
def onboarding():
    return render_template("settings.html", onboarding=True, plans=PLANS, usage=usage_summary(current_company()))


def _save_logo(file_storage, company_id):
    """Validate the upload is a real image, normalise to PNG, cap the size."""
    from PIL import Image
    data = file_storage.read()
    if not data:
        return None
    if len(data) > 1_500_000:
        raise ValueError("Logo file is too large (max 1.5 MB).")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        raise ValueError("Logo must be a PNG or JPG image.")
    img.thumbnail((600, 300))
    folder = os.path.join(current_app.config["UPLOAD_DIR"], str(company_id))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "logo.png")
    img.save(path, "PNG")
    return path


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@roles_required("owner", "admin")
def settings():
    c = current_company()
    db = get_db()
    if request.method == "POST":
        f = request.form
        vat_registered = 1 if f.get("vat_registered") == "yes" else 0
        vat_number = f.get("vat_number", "").strip()
        if vat_registered and not vat_number:
            flash("Enter your VAT number, or switch VAT status to 'Not VAT registered'.", "error")
            return render_template("settings.html", plans=PLANS, usage=usage_summary(c),
                                   onboarding=f.get("onboarding") == "1"), 400
        if f.get("vat_confirm") != "1":
            flash("Please confirm your VAT settings. QuoteFlow applies exactly what you set here.", "error")
            return render_template("settings.html", plans=PLANS, usage=usage_summary(c),
                                   onboarding=f.get("onboarding") == "1"), 400
        try:
            validity = max(1, min(365, int(f.get("validity_days", "14"))))
            retention = max(1, min(365, int(f.get("retention_days", "30"))))
        except ValueError:
            validity, retention = 14, 30
        lang = f.get("preferred_lang", "en")
        if lang not in ("en", "ar", "both"):
            lang = "en"
        logo_path = c["logo_path"]
        file = request.files.get("logo")
        if file and file.filename:
            try:
                logo_path = _save_logo(file, c["id"]) or logo_path
            except ValueError as e:
                flash(str(e), "error")
                return render_template("settings.html", plans=PLANS, usage=usage_summary(c)), 400
        before = {k: c[k] for k in ("vat_registered", "vat_number", "vat_rate_bp", "retention_days")}
        db.execute(
            """UPDATE companies SET name_en=?, name_ar=?, cr_number=?, vat_registered=?, vat_number=?,
               vat_rate_bp=?, vat_confirmed_at=datetime('now'), phone=?, email=?, address=?,
               default_terms_en=?, default_terms_ar=?, validity_days=?, preferred_lang=?,
               retention_days=?, logo_path=? WHERE id=?""",
            (f.get("name_en", "").strip() or c["name_en"], f.get("name_ar", "").strip(),
             f.get("cr_number", "").strip(), vat_registered, vat_number,
             _percent_to_bp(f.get("vat_rate", "10")), f.get("phone", "").strip(), f.get("email", "").strip(),
             f.get("address", "").strip(), f.get("default_terms_en", "").strip(),
             f.get("default_terms_ar", "").strip(), validity, lang, retention, logo_path, c["id"]),
        )
        audit.log(c["id"], current_user()["id"], "company", c["id"], "update_settings",
                  {"before": before, "vat_registered": vat_registered,
                   "vat_rate_bp": _percent_to_bp(f.get("vat_rate", "10")), "retention_days": retention})
        db.commit()
        flash("Company profile saved.", "ok")
        if f.get("onboarding") == "1":
            return redirect(url_for("catalogue.index"))
        return redirect(url_for("main.settings"))
    return render_template("settings.html", plans=PLANS, usage=usage_summary(c), onboarding=False)


@bp.route("/settings/plan", methods=["POST"])
@login_required
@roles_required("owner")
def change_plan():
    """Billing is stubbed: this just switches the plan so limits can be demonstrated."""
    plan = request.form.get("plan")
    c = current_company()
    if plan in PLANS and plan != c["plan"]:
        get_db().execute("UPDATE companies SET plan=? WHERE id=?", (plan, c["id"]))
        audit.log(c["id"], current_user()["id"], "company", c["id"], "change_plan",
                  {"from": c["plan"], "to": plan, "note": "billing stubbed"})
        get_db().commit()
        flash(f"Plan changed to {PLANS[plan]['name']} (demo: no payment taken).", "ok")
    return redirect(url_for("main.settings"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    """Change your own username and/or password (needs the current password)."""
    from werkzeug.security import check_password_hash, generate_password_hash
    from .views_auth import USERNAME_RE
    u, c, db = current_user(), current_company(), get_db()
    if request.method == "POST":
        if not check_password_hash(u["password_hash"], request.form.get("current", "")):
            flash("Your current password is not correct.", "error")
            return redirect(url_for("main.account"))
        new_user = request.form.get("username", "").strip()
        new_pw = request.form.get("password", "")
        if new_pw and len(new_pw) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("main.account"))
        if new_user and new_user.lower() != (u["username"] or "").lower():
            if not USERNAME_RE.match(new_user):
                flash("Username must be 3-30 characters: letters, numbers, dot, dash or underscore.", "error")
                return redirect(url_for("main.account"))
            if db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?) AND id<>?", (new_user, u["id"])).fetchone():
                flash("That username is taken. Please choose another.", "error")
                return redirect(url_for("main.account"))
            db.execute("UPDATE users SET username=? WHERE id=?", (new_user, u["id"]))
        if new_pw:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), u["id"]))
        audit.log(c["id"], u["id"], "user", u["id"], "account_updated", {"username": bool(new_user), "password": bool(new_pw)})
        db.commit()
        flash("Account updated.", "ok")
        return redirect(url_for("main.account"))
    return render_template("account.html", u=u)


@bp.route("/logo")
@login_required
def logo():
    c = current_company()
    if not c["logo_path"] or not os.path.exists(c["logo_path"]):
        abort(404)
    return send_file(c["logo_path"], mimetype="image/png", max_age=60)


@bp.route("/audit")
@login_required
@roles_required("owner", "admin")
def audit_view():
    c = current_company()
    rows = get_db().execute(
        """SELECT a.*, u.email AS user_email FROM audit_log a LEFT JOIN users u ON u.id=a.user_id
           WHERE a.company_id=? ORDER BY a.id DESC LIMIT 200""", (c["id"],)).fetchall()
    return render_template("audit.html", rows=rows)
