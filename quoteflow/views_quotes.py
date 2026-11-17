import json
import secrets
from datetime import date, timedelta
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app)
from .db import get_db
from . import audit
from .ai import run_extraction
from .money import (compute_quote, LineInput, parse_bhd, parse_quantity, parse_percent_bp, format_bhd,
                    format_quantity, MoneyError)
from .retention import purge_date
from .security import login_required, current_company, current_user, get_owned
from .timeutil import utcnow
from .usage import usage_summary, can_create_quote, record_quote_created
from . import docs, mailer

bp = Blueprint("quotes", __name__)

STATUSES = ["draft", "sent", "follow_up", "accepted", "rejected", "expired"]
STATUS_LABEL = {"draft": "Draft", "sent": "Sent", "follow_up": "Follow-up", "accepted": "Accepted",
                "rejected": "Rejected", "expired": "Expired"}
FEEDBACK = {"as_is": "Usable as-is", "minor": "Minor changes", "major": "Major changes", "unusable": "Unusable"}


# ------------------------------------------------------------------ helpers
def _catalogue(cid):
    rows = get_db().execute("SELECT * FROM services WHERE company_id=? AND active=1 ORDER BY id", (cid,)).fetchall()
    return [dict(r) for r in rows]


def _next_number(db, company):
    db.execute("UPDATE companies SET quote_seq = quote_seq + 1 WHERE id=?", (company["id"],))
    seq = db.execute("SELECT quote_seq FROM companies WHERE id=?", (company["id"],)).fetchone()["quote_seq"]
    return f"Q-{utcnow().year}-{seq:04d}"


def load_quote(qid, cid):
    db = get_db()
    q = get_owned("quotes", qid, cid)
    if not q:
        abort(404)
    items = [dict(r) for r in db.execute(
        "SELECT * FROM quote_items WHERE quote_id=? AND company_id=? ORDER BY position, id", (qid, cid))]
    cust = None
    if q["customer_id"]:
        row = db.execute("SELECT * FROM customers WHERE id=? AND company_id=?", (q["customer_id"], cid)).fetchone()
        cust = dict(row) if row else None
    return q, items, cust


def selected_ids(quote):
    """Optional add-on item ids the customer chose (stored as '12,15')."""
    raw = (quote["selected_optional"] if "selected_optional" in quote.keys() else "") or ""
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def is_included(item, selected):
    return not item.get("optional") or item.get("id") in selected


def totals_for(company, quote, items, selected=None):
    """Totals for the base items plus any optional add-ons the customer selected.
    Unselected optional items stay in the list with quantity 0, so line results still line up with `items`."""
    sel = selected_ids(quote) if selected is None else set(selected)
    lines = [LineInput(i["quantity_milli"] if is_included(i, sel) else 0,
                       i["unit_price_fils"] if (is_included(i, sel) or i["unit_price_fils"] is not None) else 0,
                       i["tax_class"]) for i in items]
    return compute_quote(lines, quote["discount_type"], quote["discount_value"],
                         bool(company["vat_registered"]), company["vat_rate_bp"])


def persist_totals(db, company, quote, items):
    t = totals_for(company, quote, items)
    db.execute("""UPDATE quotes SET subtotal_fils=?, discount_fils=?, vat_fils=?, total_fils=?, updated_at=datetime('now')
                  WHERE id=? AND company_id=?""",
               (t.subtotal_fils, t.discount_fils, t.vat_fils, t.total_fils, quote["id"], company["id"]))
    return t


def effective_status(q):
    """A sent / follow-up quote past its validity date shows as Expired (drafts were never sent, so they stay drafts)."""
    if q["status"] in ("sent", "follow_up") and q["valid_until"] and q["valid_until"] < date.today().isoformat():
        return "expired"
    return q["status"]


# ------------------------------------------------------------------ enquiry intake + review
@bp.route("/enquiries/new", methods=["GET", "POST"])
@login_required
def new_enquiry():
    c = current_company()
    usage = usage_summary(c)
    if request.method == "POST":
        text = (request.form.get("text") or "").strip()
        if not can_create_quote(c):
            flash("You have reached this month's quote limit for your plan. Upgrade in Settings to continue.", "error")
            return render_template("enquiry_new.html", usage=usage, text=text), 403
        if not text:
            flash("Paste the customer's message first.", "error")
            return render_template("enquiry_new.html", usage=usage, text=text), 400
        if len(text) > current_app.config["MAX_ENQUIRY_CHARS"]:
            flash(f"That message is too long (max {current_app.config['MAX_ENQUIRY_CHARS']} characters).", "error")
            return render_template("enquiry_new.html", usage=usage, text=text), 400
        catalogue = _catalogue(c["id"])
        try:
            result = run_extraction(text, catalogue, current_app.config, max_chars=current_app.config["MAX_ENQUIRY_CHARS"])
        except ValueError as e:
            flash(str(e), "error")
            return render_template("enquiry_new.html", usage=usage, text=text), 400
        db = get_db()
        cur = db.execute(
            """INSERT INTO enquiries (company_id, raw_text, purge_after, extraction_json, provider, created_by)
               VALUES (?,?,?,?,?,?)""",
            (c["id"], text, purge_date(c["retention_days"]), json.dumps(result, ensure_ascii=False),
             result["provider"], current_user()["id"]))
        audit.log(c["id"], current_user()["id"], "enquiry", cur.lastrowid, "extract",
                  {"provider": result["provider"], "items": len(result["items"]),
                   "price_events_blocked": len(result["guard"]["removed"])})
        db.commit()
        return redirect(url_for("quotes.review_enquiry", eid=cur.lastrowid))
    return render_template("enquiry_new.html", usage=usage, text="")


def _whatsapp_text(extraction, questions, lang, company_name, customer_name):
    greet_en = f"Hello{' ' + customer_name if customer_name else ''}, thank you for contacting {company_name}. " \
               "To prepare your quotation, could you please confirm:"
    greet_ar = f"السلام عليكم{' ' + customer_name if customer_name else ''}، شكراً لتواصلكم مع {company_name}. " \
               "لتجهيز عرض السعر، نرجو تأكيد التالي:"
    parts = []
    if lang in ("en", "both"):
        parts.append(greet_en + "\n" + "\n".join(f"{i}. {q['en']}" for i, q in enumerate(questions, 1)))
    if lang in ("ar", "both"):
        parts.append(greet_ar + "\n" + "\n".join(f"{i}. {q['ar'] or q['en']}" for i, q in enumerate(questions, 1)))
    return "\n\n".join(parts)


@bp.route("/enquiries/<int:eid>")
@login_required
def review_enquiry(eid):
    c = current_company()
    e = get_owned("enquiries", eid, c["id"])
    if not e or not e["extraction_json"]:
        abort(404)
    ex = json.loads(e["extraction_json"])
    existing = get_db().execute("SELECT id FROM quotes WHERE enquiry_id=? AND company_id=?", (eid, c["id"])).fetchone()
    services = {s["id"]: s for s in _catalogue(c["id"])}
    cust = ex["customer"]
    lang = "ar" if ex["language"] == "ar" else ("both" if ex["language"] == "mixed" else "en")
    wa = _whatsapp_text(ex, ex["questions"], lang, c["name_en"], cust["name"]["value"] or "")
    phone_digits = "".join(ch for ch in (cust["phone"]["value"] or "") if ch.isdigit())
    return render_template("enquiry_review.html", e=e, ex=ex, services=services, existing=existing,
                           wa_text=wa, wa_lang=lang, phone_digits=phone_digits, usage=usage_summary(c))


@bp.route("/enquiries/<int:eid>/whatsapp-text")
@login_required
def whatsapp_text(eid):
    """Rebuild the clarification message for the chosen questions/language (manual copy, no WhatsApp API)."""
    c = current_company()
    e = get_owned("enquiries", eid, c["id"])
    if not e:
        abort(404)
    ex = json.loads(e["extraction_json"])
    chosen = set(request.args.getlist("q"))
    qs = [q for i, q in enumerate(ex["questions"]) if str(i) in chosen] if chosen else ex["questions"]
    lang = request.args.get("lang", "en")
    if lang not in ("en", "ar", "both"):
        lang = "en"
    return jsonify({"text": _whatsapp_text(ex, qs, lang, c["name_en"], ex["customer"]["name"]["value"] or "")})


@bp.route("/enquiries/<int:eid>/create-quote", methods=["POST"])
@login_required
def create_quote(eid):
    c, u, db = current_company(), current_user(), get_db()
    e = get_owned("enquiries", eid, c["id"])
    if not e or not e["extraction_json"]:
        abort(404)
    existing = db.execute("SELECT id FROM quotes WHERE enquiry_id=? AND company_id=?", (eid, c["id"])).fetchone()
    if existing:
        return redirect(url_for("quotes.view", qid=existing["id"]))
    if not can_create_quote(c):
        flash("You have reached this month's quote limit for your plan. Upgrade in Settings to continue.", "error")
        return redirect(url_for("quotes.review_enquiry", eid=eid))
    ex = json.loads(e["extraction_json"])
    f = request.form
    name, phone, loc = f.get("name", "").strip()[:120], f.get("phone", "").strip()[:40], f.get("location", "").strip()[:160]

    cust_id = None
    if phone:
        row = db.execute("SELECT id FROM customers WHERE company_id=? AND phone=?", (c["id"], phone)).fetchone()
        cust_id = row["id"] if row else None
    if cust_id:
        db.execute("""UPDATE customers SET name=CASE WHEN ?<>'' THEN ? ELSE name END,
                      location=CASE WHEN ?<>'' THEN ? ELSE location END WHERE id=? AND company_id=?""",
                   (name, name, loc, loc, cust_id, c["id"]))
    else:
        cust_id = db.execute("INSERT INTO customers (company_id, name, phone, location) VALUES (?,?,?,?)",
                             (c["id"], name, phone, loc)).lastrowid
    valid_until = (date.today() + timedelta(days=c["validity_days"])).isoformat()
    lang = f.get("language") if f.get("language") in ("en", "ar", "both") else c["preferred_lang"]
    qid = db.execute(
        """INSERT INTO quotes (company_id, enquiry_id, customer_id, number, status, language, valid_until,
           terms_en, terms_ar) VALUES (?,?,?,?, 'draft', ?,?,?,?)""",
        (c["id"], eid, cust_id, _next_number(db, c), lang, valid_until, c["default_terms_en"], c["default_terms_ar"])).lastrowid
    db.execute("UPDATE enquiries SET customer_id=? WHERE id=? AND company_id=?", (cust_id, eid, c["id"]))

    services = {s["id"]: s for s in _catalogue(c["id"])}
    for pos, it in enumerate(ex["items"]):
        svc = services.get(it["service_id"])
        price = svc["default_price_fils"] if svc else None
        origin = "customer" if (svc and it["quantity_source"] == "customer") else "ai"
        title_en = svc["name_en"] if svc else (it["customer_words"][:120] or "Item")
        title_ar = svc["name_ar"] if svc else ""
        db.execute(
            """INSERT INTO quote_items (company_id, quote_id, position, service_id, title_en, title_ar, desc_en, desc_ar,
               customer_words, quantity_milli, unit, unit_price_fils, price_source, tax_class, origin, uncertain)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c["id"], qid, pos, svc["id"] if svc else None, title_en, title_ar, it["description_en"],
             it["description_ar"], it["customer_words"], it["quantity_milli"] or 1000,
             (svc["unit"] if svc else (it["unit_hint"] or "each")), price,
             "catalogue" if (svc and price is not None) else "none", svc["tax_class"] if svc else "standard",
             origin, 1 if it["uncertain"] else 0))
    record_quote_created(c["id"])
    audit.log(c["id"], u["id"], "quote", qid, "create_draft", {"enquiry": eid, "items": len(ex["items"])})
    db.commit()
    q, items, _ = load_quote(qid, c["id"])
    persist_totals(db, c, q, items)
    db.commit()
    return redirect(url_for("quotes.view", qid=qid))


# ------------------------------------------------------------------ quote editor
@bp.route("/quotes/<int:qid>")
@login_required
def view(qid):
    c = current_company()
    q, items, cust = load_quote(qid, c["id"])
    t = totals_for(c, q, items)
    enquiry = get_owned("enquiries", q["enquiry_id"], c["id"]) if q["enquiry_id"] else None
    ex = json.loads(enquiry["extraction_json"]) if enquiry and enquiry["extraction_json"] else None
    return render_template("quote_edit.html", q=q, items=items, cust=cust, tot=t, catalogue=_catalogue(c["id"]),
                           enquiry=enquiry, ex=ex, status=effective_status(q), STATUSES=STATUSES,
                           STATUS_LABEL=STATUS_LABEL, FEEDBACK=FEEDBACK, fmt_qty=format_quantity)


def _parse_items(form, services, company_id):
    n = int(form.get("item_count", "0") or 0)
    if n < 0 or n > 60:
        raise ValueError("Too many items.")
    out = []
    for i in range(n):
        g = lambda k: form.get(f"{k}_{i}", "").strip()
        if g("delete") == "1":
            continue
        qty = parse_quantity(g("qty") or "1")
        price_txt = g("price")
        price = parse_bhd(price_txt) if price_txt else None
        tax = g("tax") if g("tax") in ("standard", "zero", "exempt") else "standard"
        sid = int(g("service_id")) if g("service_id").isdigit() else None
        svc = services.get(sid)
        if sid and not svc:
            sid = None
        src = "none" if price is None else ("catalogue" if svc and svc["default_price_fils"] == price else "manual")
        title_en, title_ar = g("title_en")[:160], g("title_ar")[:160]
        if not (title_en or title_ar):
            raise ValueError("Every item needs a name.")
        out.append({"id": int(g("item_id")) if g("item_id").isdigit() else None, "service_id": sid,
                    "title_en": title_en or title_ar, "title_ar": title_ar, "desc_en": g("desc_en")[:600],
                    "desc_ar": g("desc_ar")[:600], "customer_words": g("customer_words")[:200],
                    "quantity_milli": qty, "unit": g("unit")[:20] or "each", "unit_price_fils": price,
                    "price_source": src, "tax_class": tax, "origin": g("origin") if g("origin") in ("customer", "ai", "manual") else "manual",
                    "uncertain": 1 if g("uncertain") == "1" else 0, "approved": 1 if g("reviewed") == "1" else 0,
                    "optional": 1 if g("optional") == "1" else 0})
    return out


def _apply_edit(c, u, qid, form):
    """Validate and save the whole editor form. Returns (ok, message)."""
    db = get_db()
    q, old_items, cust = load_quote(qid, c["id"])
    services = {s["id"]: s for s in _catalogue(c["id"])}
    try:
        new_items = _parse_items(form, services, c["id"])
        dtype = form.get("discount_type", "none")
        if dtype not in ("none", "percent", "fixed"):
            dtype = "none"
        dtxt = form.get("discount_value", "").strip()
        dval = 0 if dtype == "none" or not dtxt else (parse_percent_bp(dtxt) if dtype == "percent" else parse_bhd(dtxt))
        valid = form.get("valid_until", "").strip()
        if valid:
            date.fromisoformat(valid)
        lang = form.get("language", q["language"])
        lang = lang if lang in ("en", "ar", "both") else q["language"]
    except (MoneyError, ValueError) as e:
        return False, str(e)

    # audit: commercially important changes
    old_by_id = {i["id"]: i for i in old_items}
    changes = []
    for ni in new_items:
        oi = old_by_id.get(ni["id"])
        if not oi:
            changes.append(f"added '{ni['title_en'][:40]}'")
            continue
        if oi["unit_price_fils"] != ni["unit_price_fils"]:
            changes.append(f"price '{ni['title_en'][:30]}': {format_bhd(oi['unit_price_fils'])} -> {format_bhd(ni['unit_price_fils'])}")
        if oi["quantity_milli"] != ni["quantity_milli"]:
            changes.append(f"qty '{ni['title_en'][:30]}': {format_quantity(oi['quantity_milli'])} -> {format_quantity(ni['quantity_milli'])}")
        if (oi["desc_en"], oi["desc_ar"]) != (ni["desc_en"], ni["desc_ar"]):
            changes.append(f"description '{ni['title_en'][:30]}' edited")
        if oi["tax_class"] != ni["tax_class"]:
            changes.append(f"tax '{ni['title_en'][:30]}': {oi['tax_class']} -> {ni['tax_class']}")
    kept = {i["id"] for i in new_items if i["id"]}
    for oi in old_items:
        if oi["id"] not in kept:
            changes.append(f"removed '{oi['title_en'][:40]}'")
    if (q["discount_type"], q["discount_value"]) != (dtype, dval):
        changes.append(f"discount {q['discount_type']}:{q['discount_value']} -> {dtype}:{dval}")

    # customer details
    if cust:
        db.execute("UPDATE customers SET name=?, phone=?, email=?, location=? WHERE id=? AND company_id=?",
                   (form.get("cust_name", "").strip()[:120], form.get("cust_phone", "").strip()[:40],
                    form.get("cust_email", "").strip()[:254],
                    form.get("cust_location", "").strip()[:160], cust["id"], c["id"]))
    # items: update/insert/delete
    for i in old_items:
        if i["id"] not in kept:
            db.execute("DELETE FROM quote_items WHERE id=? AND company_id=?", (i["id"], c["id"]))
    for pos, ni in enumerate(new_items):
        vals = (pos, ni["service_id"], ni["title_en"], ni["title_ar"], ni["desc_en"], ni["desc_ar"], ni["customer_words"],
                ni["quantity_milli"], ni["unit"], ni["unit_price_fils"], ni["price_source"], ni["tax_class"],
                ni["origin"], ni["uncertain"], ni["approved"], ni["optional"])
        if ni["id"] in old_by_id:
            db.execute("""UPDATE quote_items SET position=?, service_id=?, title_en=?, title_ar=?, desc_en=?, desc_ar=?,
                          customer_words=?, quantity_milli=?, unit=?, unit_price_fils=?, price_source=?, tax_class=?,
                          origin=?, uncertain=?, approved=?, optional=? WHERE id=? AND company_id=?""", (*vals, ni["id"], c["id"]))
        else:
            db.execute("""INSERT INTO quote_items (position, service_id, title_en, title_ar, desc_en, desc_ar,
                          customer_words, quantity_milli, unit, unit_price_fils, price_source, tax_class, origin,
                          uncertain, approved, optional, company_id, quote_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (*vals, c["id"], qid))
    db.execute("""UPDATE quotes SET discount_type=?, discount_value=?, valid_until=?, language=?, terms_en=?, terms_ar=?,
                  notes=?, approved_at=NULL, approved_by=NULL WHERE id=? AND company_id=?""",
               (dtype, dval, valid or None, lang, form.get("terms_en", "")[:1500], form.get("terms_ar", "")[:1500],
                form.get("notes", "")[:500], qid, c["id"]))
    q2, items2, _ = load_quote(qid, c["id"])
    persist_totals(db, c, q2, items2)
    audit.log(c["id"], u["id"], "quote", qid, "edit", "; ".join(changes)[:1800] or "saved (no commercial changes)")
    return True, ""


@bp.route("/quotes/<int:qid>/save", methods=["POST"])
@login_required
def save(qid):
    c, u, db = current_company(), current_user(), get_db()
    q, _, _ = load_quote(qid, c["id"])
    if q["approved_at"]:
        flash("This quote is approved. Unlock it to edit.", "warn")
        return redirect(url_for("quotes.view", qid=qid))
    ok, msg = _apply_edit(c, u, qid, request.form)
    if not ok:
        db.rollback()
        flash(msg, "error")
        return redirect(url_for("quotes.view", qid=qid))
    if request.form.get("action") == "approve":
        ok, msg = _approve(c, u, qid)
        if not ok:
            db.commit()
            flash("Saved, but not approved: " + msg, "warn")
            return redirect(url_for("quotes.view", qid=qid))
        db.commit()
        flash("Quote approved. You can now preview, export the PDF and share it.", "ok")
        return redirect(url_for("quotes.view", qid=qid) + "#feedback")
    db.commit()
    flash("Saved.", "ok")
    return redirect(url_for("quotes.view", qid=qid))


def _approve(c, u, qid):
    db = get_db()
    q, items, _ = load_quote(qid, c["id"])
    if not c["vat_confirmed_at"]:
        return False, "confirm your VAT settings in Settings first."
    if not items:
        return False, "add at least one item."
    t = totals_for(c, q, items)
    missing = [i["title_en"] for i in items if i["unit_price_fils"] is None]
    if missing:
        return False, "enter a price for: " + ", ".join(m[:40] for m in missing) + "."
    unreviewed = [i["title_en"] for i in items if not i["approved"]]
    if unreviewed:
        return False, "tick 'I checked this item' for: " + ", ".join(m[:40] for m in unreviewed) + "."
    if t.total_fils <= 0:
        return False, "the total is zero. Check prices and discount."
    db.execute("UPDATE quotes SET approved_at=datetime('now'), approved_by=? WHERE id=? AND company_id=?",
               (u["id"], qid, c["id"]))
    audit.log(c["id"], u["id"], "quote", qid, "approve",
              {"total_fils": t.total_fils, "vat_fils": t.vat_fils, "vat_rate_bp": c["vat_rate_bp"],
               "vat_registered": bool(c["vat_registered"])})
    return True, ""


@bp.route("/quotes/<int:qid>/unlock", methods=["POST"])
@login_required
def unlock(qid):
    c, u, db = current_company(), current_user(), get_db()
    load_quote(qid, c["id"])
    db.execute("UPDATE quotes SET approved_at=NULL, approved_by=NULL WHERE id=? AND company_id=?", (qid, c["id"]))
    audit.log(c["id"], u["id"], "quote", qid, "unlock_for_edit")
    db.commit()
    flash("Quote unlocked. It must be approved again before export.", "warn")
    return redirect(url_for("quotes.view", qid=qid))


@bp.route("/quotes/<int:qid>/feedback", methods=["POST"])
@login_required
def feedback(qid):
    c, u, db = current_company(), current_user(), get_db()
    load_quote(qid, c["id"])
    val = request.form.get("rating")
    if val in FEEDBACK:
        db.execute("UPDATE quotes SET feedback=?, feedback_at=datetime('now') WHERE id=? AND company_id=?", (val, qid, c["id"]))
        audit.log(c["id"], u["id"], "quote", qid, "feedback", {"rating": val})
        db.commit()
        flash("Thanks! This helps us improve the AI drafts.", "ok")
    return redirect(url_for("quotes.view", qid=qid))


@bp.route("/quotes/totals", methods=["POST"])
@login_required
def live_totals():
    """The browser asks the server (money.py) for totals; there is no second copy of the maths in JavaScript."""
    c = current_company()
    data = request.get_json(silent=True) or {}
    try:
        lines = []
        for it in data.get("items", [])[:60]:
            price = it.get("price", "").strip()
            qty = parse_quantity(it.get("qty") or "1")
            if it.get("optional"):
                qty = 0          # optional add-ons are not in the base total until the customer picks them
                price = price or "0"
            lines.append(LineInput(qty, parse_bhd(price) if price else None,
                                   it.get("tax") if it.get("tax") in ("standard", "zero", "exempt") else "standard"))
        dtype = data.get("discount_type", "none")
        dtxt = (data.get("discount_value") or "").strip()
        dval = 0 if dtype == "none" or not dtxt else (parse_percent_bp(dtxt) if dtype == "percent" else parse_bhd(dtxt))
        t = compute_quote(lines, dtype if dtype in ("none", "percent", "fixed") else "none", dval,
                          bool(c["vat_registered"]), c["vat_rate_bp"])
    except (MoneyError, ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 200
    return jsonify({"lines": [format_bhd(r.line_total_fils) for r in t.lines], "subtotal": format_bhd(t.subtotal_fils),
                    "discount": format_bhd(t.discount_fils), "vat": format_bhd(t.vat_fils),
                    "total": format_bhd(t.total_fils), "complete": t.complete, "warnings": t.warnings,
                    "vat_applied": t.vat_applied})


@bp.app_template_global()
def ai_mode():
    from .ai import pick_provider
    return pick_provider(current_app.config).name


@bp.route("/quotes/<int:qid>/status", methods=["POST"])
@login_required
def set_status(qid):
    c, u, db = current_company(), current_user(), get_db()
    q, _, _ = load_quote(qid, c["id"])
    new = request.form.get("status")
    if new not in STATUSES:
        abort(400)
    if new in ("sent", "follow_up", "accepted") and not q["approved_at"]:
        flash("Approve the quote before marking it as sent.", "error")
        return redirect(url_for("quotes.view", qid=qid))
    db.execute("UPDATE quotes SET status=?, sent_at=CASE WHEN ?='sent' AND sent_at IS NULL THEN datetime('now') ELSE sent_at END, "
               "updated_at=datetime('now') WHERE id=? AND company_id=?", (new, new, qid, c["id"]))
    audit.log(c["id"], u["id"], "quote", qid, "status", {"from": q["status"], "to": new})
    db.commit()
    flash(f"Status set to {STATUS_LABEL[new]}.", "ok")
    return redirect(url_for("quotes.view", qid=qid))


# ------------------------------------------------------------------ preview / PDF / share (approved quotes only)
def _approved_or_redirect(qid, c):
    q, items, cust = load_quote(qid, c["id"])
    if not q["approved_at"]:
        return None, None, None, None
    return q, items, cust, totals_for(c, q, items)


def _lang_arg(q):
    lang = request.args.get("lang", q["language"])
    return lang if lang in ("en", "ar", "both") else q["language"]


@bp.route("/quotes/<int:qid>/document")
@login_required
def document(qid):
    c = current_company()
    q, items, cust, tot = _approved_or_redirect(qid, c)
    if not q:
        abort(404)
    return docs.render_document(c, q, items, tot, cust, _lang_arg(q))


@bp.route("/quotes/<int:qid>/preview")
@login_required
def preview(qid):
    c = current_company()
    q, items, cust, tot = _approved_or_redirect(qid, c)
    if not q:
        flash("Approve the quote first. Only approved quotes can be previewed and exported.", "warn")
        return redirect(url_for("quotes.view", qid=qid))
    return render_template("quote_preview.html", q=q, lang=_lang_arg(q))


@bp.route("/quotes/<int:qid>/pdf")
@login_required
def pdf(qid):
    from flask import Response
    c, u = current_company(), current_user()
    q, items, cust, tot = _approved_or_redirect(qid, c)
    if not q:
        abort(404)
    lang = _lang_arg(q)
    html = docs.render_document(c, q, items, tot, cust, lang)
    try:
        data = docs.html_to_pdf(html)
    except docs.PdfUnavailable as e:
        flash(f"{e} You can still use Print and choose 'Save as PDF'.", "error")
        return redirect(url_for("quotes.preview", qid=qid, lang=lang))
    audit.log(c["id"], u["id"], "quote", qid, "export_pdf", {"lang": lang, "total_fils": tot.total_fils})
    get_db().commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{q["number"]}-{lang}.pdf"'})


def _share_link(q):
    tok = q["share_token"] if "share_token" in q.keys() else None
    return url_for("public.view", token=tok, _external=True) if tok else None


@bp.route("/quotes/<int:qid>/link", methods=["POST"])
@login_required
def create_link(qid):
    """Create (or keep) the interactive customer link. Only for approved quotes."""
    c, u, db = current_company(), current_user(), get_db()
    q, _, _ = load_quote(qid, c["id"])
    if not q["approved_at"]:
        flash("Approve the quote first.", "warn")
        return redirect(url_for("quotes.view", qid=qid))
    if not q["share_token"]:
        db.execute("UPDATE quotes SET share_token=? WHERE id=? AND company_id=?", (secrets.token_urlsafe(24), qid, c["id"]))
        audit.log(c["id"], u["id"], "quote", qid, "link_created", {})
        db.commit()
    flash("Customer link created. Copy it into WhatsApp or email.", "ok")
    return redirect(url_for("quotes.share", qid=qid))


@bp.route("/quotes/<int:qid>/link/revoke", methods=["POST"])
@login_required
def revoke_link(qid):
    c, u, db = current_company(), current_user(), get_db()
    load_quote(qid, c["id"])
    db.execute("UPDATE quotes SET share_token=NULL WHERE id=? AND company_id=?", (qid, c["id"]))
    audit.log(c["id"], u["id"], "quote", qid, "link_revoked", {})
    db.commit()
    flash("Customer link turned off. The old link no longer works.", "ok")
    return redirect(url_for("quotes.share", qid=qid))


@bp.route("/quotes/<int:qid>/share")
@login_required
def share(qid):
    c = current_company()
    q, items, cust, tot = _approved_or_redirect(qid, c)
    if not q:
        flash("Approve the quote first. Only approved quotes can be shared.", "warn")
        return redirect(url_for("quotes.view", qid=qid))
    lang = _lang_arg(q)
    link = _share_link(q)
    text = docs.share_text(c, q, items, tot, cust, lang, link=link)
    digits = "".join(ch for ch in ((cust or {}).get("phone") or "") if ch.isdigit())
    if len(digits) == 8:          # local Bahrain number -> add the country code for wa.me
        digits = "973" + digits
    return render_template("quote_share.html", q=q, lang=lang, text=text, digits=digits, cust=cust,
                           mail_ready=mailer.mail_enabled(current_app.config), company=c, link=link,
                           n_optional=sum(1 for i in items if i.get("optional")))


@bp.route("/quotes/<int:qid>/send-email", methods=["POST"])
@login_required
def send_email(qid):
    """One click, after the owner has approved the quote: email the PDF to the customer."""
    c, u, db = current_company(), current_user(), get_db()
    q, items, cust, tot = _approved_or_redirect(qid, c)
    if not q:
        flash("Approve the quote first. Only approved quotes can be sent.", "warn")
        return redirect(url_for("quotes.view", qid=qid))
    lang = request.form.get("lang", q["language"])
    if lang not in ("en", "ar", "both"):
        lang = q["language"]
    to = request.form.get("to", "").strip()
    if not mailer.valid_email(to):
        flash("Enter a valid customer email address.", "error")
        return redirect(url_for("quotes.share", qid=qid, lang=lang))
    try:
        data = docs.html_to_pdf(docs.render_document(c, q, items, tot, cust, lang))
        body = docs.share_text(c, q, items, tot, cust, lang, link=_share_link(q))
        mailer.send_quote_email(
            current_app.config, to=to, company_name=c["name_en"] or c["name_ar"], reply_to=c["email"],
            subject=f"Quotation {q['number']} - {c['name_en'] or c['name_ar']}", body=body,
            pdf_bytes=data, pdf_name=f"{q['number']}-{lang}.pdf")
    except (docs.PdfUnavailable, mailer.MailError) as e:
        flash(str(e), "error")
        return redirect(url_for("quotes.share", qid=qid, lang=lang))
    if cust and not (cust["email"] or ""):
        db.execute("UPDATE customers SET email=? WHERE id=? AND company_id=?", (to, cust["id"], c["id"]))
    db.execute("UPDATE quotes SET status=CASE WHEN status='draft' THEN 'sent' ELSE status END, "
               "sent_at=COALESCE(sent_at, datetime('now')), updated_at=datetime('now') WHERE id=? AND company_id=?",
               (qid, c["id"]))
    audit.log(c["id"], u["id"], "quote", qid, "email_sent", {"lang": lang, "total_fils": tot.total_fils})
    db.commit()
    flash(f"Quotation emailed to {to}. Marked as Sent.", "ok")
    return redirect(url_for("quotes.share", qid=qid, lang=lang))


@bp.route("/quotes/<int:qid>/whatsapp-sent", methods=["POST"])
@login_required
def whatsapp_sent(qid):
    """Called when the owner opens WhatsApp from the share page: records it and marks Sent."""
    c, u, db = current_company(), current_user(), get_db()
    q, _, _ = load_quote(qid, c["id"])
    if not q["approved_at"]:
        abort(400)
    db.execute("UPDATE quotes SET status=CASE WHEN status='draft' THEN 'sent' ELSE status END, "
               "sent_at=COALESCE(sent_at, datetime('now')), updated_at=datetime('now') WHERE id=? AND company_id=?",
               (qid, c["id"]))
    audit.log(c["id"], u["id"], "quote", qid, "whatsapp_opened", {})
    db.commit()
    return ("", 204)


# ------------------------------------------------------------------ history + customers
def _like(term):
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@bp.route("/quotes")
@login_required
def history():
    c, db = current_company(), get_db()
    term = (request.args.get("q") or "").strip()[:80]
    status = request.args.get("status", "")
    cust_id = request.args.get("customer", type=int)
    base = """SELECT q.*, cu.name AS customer_name, cu.phone AS customer_phone, cu.location AS customer_location,
              CASE WHEN q.status IN ('sent','follow_up') AND q.valid_until IS NOT NULL AND q.valid_until < date('now')
                   THEN 'expired' ELSE q.status END AS eff_status
              FROM quotes q LEFT JOIN customers cu ON cu.id=q.customer_id WHERE q.company_id=?"""
    args = [c["id"]]
    if term:
        base += """ AND (q.number LIKE ? ESCAPE '\\' OR cu.name LIKE ? ESCAPE '\\' OR cu.phone LIKE ? ESCAPE '\\'
                    OR cu.location LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM quote_items i WHERE i.quote_id=q.id
                    AND (i.title_en LIKE ? ESCAPE '\\' OR i.title_ar LIKE ? ESCAPE '\\')))"""
        args += [_like(term)] * 6
    if cust_id:
        base += " AND q.customer_id=?"
        args.append(cust_id)
    rows = db.execute(f"SELECT * FROM ({base}) WHERE 1=1 " + ("AND eff_status=? " if status in STATUSES else "") +
                      "ORDER BY id DESC LIMIT 100", args + ([status] if status in STATUSES else [])).fetchall()
    counts = {r["s"]: r["n"] for r in db.execute(f"SELECT eff_status s, COUNT(*) n FROM ({base}) GROUP BY eff_status", args)}
    return render_template("history.html", rows=rows, term=term, status=status, counts=counts, STATUSES=STATUSES,
                           STATUS_LABEL=STATUS_LABEL, cust_id=cust_id)


@bp.route("/customers")
@login_required
def customers():
    c, db = current_company(), get_db()
    term = (request.args.get("q") or "").strip()[:80]
    sql = """SELECT cu.*, COUNT(q.id) AS n_quotes, COALESCE(SUM(CASE WHEN q.status='accepted' THEN q.total_fils END),0) AS won_fils
             FROM customers cu LEFT JOIN quotes q ON q.customer_id=cu.id AND q.company_id=cu.company_id
             WHERE cu.company_id=?"""
    args = [c["id"]]
    if term:
        sql += " AND (cu.name LIKE ? ESCAPE '\\' OR cu.phone LIKE ? ESCAPE '\\' OR cu.location LIKE ? ESCAPE '\\')"
        args += [_like(term)] * 3
    rows = db.execute(sql + " GROUP BY cu.id ORDER BY cu.id DESC LIMIT 200", args).fetchall()
    return render_template("customers.html", rows=rows, term=term)
