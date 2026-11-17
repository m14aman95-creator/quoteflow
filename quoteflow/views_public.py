"""Interactive customer quotation page (public, token link).

The customer can read the quote, choose optional add-ons (totals are recalculated by the server, never in the browser),
accept it by typing their name, decline it, ask a question on WhatsApp, or download the PDF.
Only APPROVED quotes are reachable. The token is random and unguessable; the owner can revoke it at any time."""
import time
from datetime import date
from flask import Blueprint, render_template, request, abort, jsonify, Response, current_app, redirect, url_for
from .db import get_db
from . import audit, docs, mailer
from .money import compute_quote, LineInput, format_bhd, format_quantity
from .security import current_company
from .views_quotes import totals_for, selected_ids

bp = Blueprint("public", __name__)

# ---- tiny in-memory rate limit (per IP): enough to stop a link being hammered
_HITS = {}


def _limited(kind, limit, window=60):
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "") or "").split(",")[0].strip()
    now = time.time()
    key = (kind, ip)
    hits = [t for t in _HITS.get(key, []) if now - t < window]
    if len(hits) >= limit:
        _HITS[key] = hits
        return True
    hits.append(now)
    _HITS[key] = hits
    if len(_HITS) > 5000:
        _HITS.clear()
    return False


UI = {
    "en": {
        "quote": "Quotation", "for": "Prepared for", "valid": "Valid until", "left": "{n} days left", "today": "Last day",
        "expired": "This quotation has expired. Please contact us for an updated one.",
        "included": "What is included", "optional": "Optional add-ons", "optional_hint": "Tick anything you would like to add. Your total updates instantly.",
        "subtotal": "Subtotal", "discount": "Discount", "vat": "VAT", "total": "Total", "notvat": "VAT not applicable",
        "accept": "Accept quotation", "decline": "Decline", "ask": "Ask a question", "pdf": "Download PDF",
        "your_name": "Your full name", "agree": "I accept this quotation and its terms.", "confirm": "Confirm acceptance",
        "reason": "Reason (optional)", "send_decline": "Send", "cancel": "Cancel", "terms": "Terms & conditions", "notes": "Note",
        "accepted_by": "Accepted by {name} on {date}. Thank you! We will be in touch to confirm the details.",
        "declined": "You declined this quotation. If that was a mistake, please contact us.",
        "chosen": "Add-ons you chose", "none": "No add-ons selected", "qty": "Qty", "each": "each",
        "name_needed": "Please type your full name and tick the box to accept.", "currency": "BHD", "added": "Added",
        "hello": "Hello {name}", "intro": "Here is your quotation from {co}. Review it, choose any add-ons, then accept when you are ready.",
        "wa_q": "Hello, I have a question about quotation {no}.", "secure": "Prepared by {co}. Prices are set by {co}.",
    },
    "ar": {
        "quote": "عرض سعر", "for": "مقدم إلى", "valid": "صالح حتى", "left": "باقي {n} يوم", "today": "آخر يوم",
        "expired": "انتهت صلاحية هذا العرض. يرجى التواصل معنا للحصول على عرض محدث.",
        "included": "ما يشمله العرض", "optional": "إضافات اختيارية", "optional_hint": "حدد ما تريد إضافته. يتحدث الإجمالي فوراً.",
        "subtotal": "المجموع الفرعي", "discount": "الخصم", "vat": "ضريبة القيمة المضافة", "total": "الإجمالي", "notvat": "لا تنطبق ضريبة القيمة المضافة",
        "accept": "الموافقة على العرض", "decline": "رفض", "ask": "اسأل سؤالاً", "pdf": "تحميل PDF",
        "your_name": "اسمك الكامل", "agree": "أوافق على عرض السعر وشروطه.", "confirm": "تأكيد الموافقة",
        "reason": "السبب (اختياري)", "send_decline": "إرسال", "cancel": "إلغاء", "terms": "الشروط والأحكام", "notes": "ملاحظة",
        "accepted_by": "تمت الموافقة من {name} بتاريخ {date}. شكراً لك! سنتواصل معك لتأكيد التفاصيل.",
        "declined": "لقد رفضت هذا العرض. إذا كان ذلك بالخطأ، يرجى التواصل معنا.",
        "chosen": "الإضافات التي اخترتها", "none": "لم يتم اختيار إضافات", "qty": "الكمية", "each": "للوحدة",
        "name_needed": "يرجى كتابة اسمك الكامل ووضع علامة للموافقة.", "currency": "د.ب", "added": "تمت الإضافة",
        "hello": "مرحباً {name}", "intro": "هذا عرض السعر المقدم من {co}. راجعه، واختر الإضافات إن أردت، ثم وافق عليه عندما تكون جاهزاً.",
        "wa_q": "السلام عليكم، لدي سؤال بخصوص عرض السعر {no}.", "secure": "أعده {co}. الأسعار من تحديد {co}.",
    },
}


def _load(token):
    if not token or len(token) < 20 or len(token) > 80:
        abort(404)
    db = get_db()
    q = db.execute("SELECT * FROM quotes WHERE share_token=?", (token,)).fetchone()
    if not q or not q["approved_at"]:
        abort(404)
    q = dict(q)
    co = dict(db.execute("SELECT * FROM companies WHERE id=?", (q["company_id"],)).fetchone())
    items = [dict(r) for r in db.execute(
        "SELECT * FROM quote_items WHERE quote_id=? AND company_id=? ORDER BY position, id", (q["id"], q["company_id"]))]
    cust = None
    if q["customer_id"]:
        r = db.execute("SELECT * FROM customers WHERE id=? AND company_id=?", (q["customer_id"], q["company_id"])).fetchone()
        cust = dict(r) if r else None
    return q, co, items, cust


def _responded(q):
    return q["status"] in ("accepted", "rejected") and bool(q["responded_at"])


def _expired(q):
    return bool(q["valid_until"]) and q["valid_until"] < date.today().isoformat()


def _lang():
    lg = request.values.get("lang", "")
    return lg if lg in ("en", "ar") else None


def _valid_selection(items, ids):
    ok = {i["id"] for i in items if i["optional"]}
    return {int(x) for x in ids if str(x).isdigit() and int(x) in ok}


def _quiet(resp):
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def _totals_payload(co, q, items, selected):
    t = totals_for(co, q, items, selected)
    return t, {"subtotal": format_bhd(t.subtotal_fils), "discount": format_bhd(t.discount_fils), "vat": format_bhd(t.vat_fils),
               "total": format_bhd(t.total_fils), "vat_applied": t.vat_applied,
               "lines": [format_bhd(r.line_total_fils) for r in t.lines]}


@bp.route("/q/<token>")
def view(token):
    q, co, items, cust = _load(token)
    db = get_db()
    lang = _lang() or ("ar" if q["language"] == "ar" else "en")
    mine = current_company()
    if not (mine and mine["id"] == q["company_id"]):        # the owner previewing the link is not a customer view
        db.execute("UPDATE quotes SET view_count=view_count+1, viewed_at=datetime('now') WHERE id=?", (q["id"],))
        if not q["view_count"]:
            audit.log(q["company_id"], None, "quote", q["id"], "customer_viewed", {})
        db.commit()
    responded = _responded(q)
    selected = selected_ids(q) if responded else set()
    t, pay = _totals_payload(co, q, items, selected)
    expired = _expired(q) and not responded
    days_left = None
    if q["valid_until"] and not expired:
        days_left = (date.fromisoformat(q["valid_until"]) - date.today()).days
    base = [(it, t.lines[i]) for i, it in enumerate(items) if not it["optional"]]
    opts = []
    for i, it in enumerate(items):
        if it["optional"]:
            one = compute_quote([LineInput(it["quantity_milli"], it["unit_price_fils"], it["tax_class"])], "none", 0, False, 0)
            opts.append((it, one.lines[0].line_total_fils, it["id"] in selected))
    digits = "".join(ch for ch in (co.get("phone") or "") if ch.isdigit())
    if len(digits) == 8:
        digits = "973" + digits
    resp = Response(render_template(
        "quote_public.html", q=q, co=co, items=items, cust=cust, lang=lang, P=UI[lang], t=t, pay=pay, base=base, opts=opts,
        responded=responded, expired=expired, days_left=days_left, selected=selected, token=token, digits=digits,
        logo=docs._logo_data_uri(co.get('logo_path')), fmt_qty=format_quantity, unit_ar=docs.UNIT_AR, dir="rtl" if lang == "ar" else "ltr", can_act=not responded and not expired))
    return _quiet(resp)


@bp.route("/q/<token>/totals", methods=["POST"])
def totals(token):
    if _limited("totals", 120):
        return jsonify({"error": "slow down"}), 429
    q, co, items, _ = _load(token)
    data = request.get_json(silent=True) or {}
    sel = _valid_selection(items, data.get("selected", [])[:60] if isinstance(data.get("selected"), list) else [])
    _, pay = _totals_payload(co, q, items, sel)
    return _quiet(jsonify(pay))


def _notify(co, q, subject, body):
    if co.get("email"):
        mailer.send_notice(current_app.config, to=co["email"], subject=subject, body=body)


@bp.route("/q/<token>/accept", methods=["POST"])
def accept(token):
    if _limited("respond", 10):
        abort(429)
    q, co, items, cust = _load(token)
    lang = _lang() or "en"
    if _responded(q) or _expired(q):
        return redirect(url_for("public.view", token=token, lang=lang))
    name = request.form.get("name", "").strip()[:120]
    if not name or request.form.get("agree") != "1":
        return redirect(url_for("public.view", token=token, lang=lang, err=1) + "#accept")
    sel = _valid_selection(items, request.form.getlist("opt"))
    db = get_db()
    t = totals_for(co, q, items, sel)
    db.execute("""UPDATE quotes SET status='accepted', responded_at=datetime('now'), response_name=?, selected_optional=?,
                  subtotal_fils=?, discount_fils=?, vat_fils=?, total_fils=?, updated_at=datetime('now')
                  WHERE id=? AND company_id=?""",
               (name, ",".join(str(i) for i in sorted(sel)), t.subtotal_fils, t.discount_fils, t.vat_fils, t.total_fils,
                q["id"], q["company_id"]))
    audit.log(q["company_id"], None, "quote", q["id"], "customer_accepted",
              {"name": name, "optional_ids": sorted(sel), "total_fils": t.total_fils})
    db.commit()
    _notify(co, q, f"Quotation {q['number']} accepted by {name}",
            f"{name} accepted quotation {q['number']} online.\nTotal: {format_bhd(t.total_fils)} BHD"
            f"{' (including ' + str(len(sel)) + ' optional add-on(s))' if sel else ''}.\nOpen QuoteFlow to follow up.")
    return redirect(url_for("public.view", token=token, lang=lang))


@bp.route("/q/<token>/decline", methods=["POST"])
def decline(token):
    if _limited("respond", 10):
        abort(429)
    q, co, items, _ = _load(token)
    lang = _lang() or "en"
    if _responded(q):
        return redirect(url_for("public.view", token=token, lang=lang))
    note = request.form.get("reason", "").strip()[:300]
    db = get_db()
    db.execute("UPDATE quotes SET status='rejected', responded_at=datetime('now'), response_note=?, updated_at=datetime('now') "
               "WHERE id=? AND company_id=?", (note, q["id"], q["company_id"]))
    audit.log(q["company_id"], None, "quote", q["id"], "customer_declined", {"note": note})
    db.commit()
    _notify(co, q, f"Quotation {q['number']} declined",
            f"The customer declined quotation {q['number']}.\nReason: {note or 'none given'}")
    return redirect(url_for("public.view", token=token, lang=lang))


@bp.route("/q/<token>/pdf")
def pdf(token):
    if _limited("pdf", 12):
        abort(429)
    q, co, items, cust = _load(token)
    lang = _lang() or ("ar" if q["language"] == "ar" else "en")
    if not _responded(q) and request.args.get("sel") is not None:
        sel = _valid_selection(items, request.args.get("sel", "").split(","))
        q["selected_optional"] = ",".join(str(i) for i in sorted(sel))
    t = totals_for(co, q, items)
    html = docs.render_document(co, q, items, t, cust, lang)
    try:
        data = docs.html_to_pdf(html)
    except docs.PdfUnavailable:
        abort(503)
    resp = Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{q["number"]}-{lang}.pdf"'})
    return _quiet(resp)
