from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from .db import get_db
from . import audit
from .money import parse_bhd, MoneyError, format_bhd
from .security import login_required, current_company, current_user, get_owned
from .seed_data import STARTER_PACKS

bp = Blueprint("catalogue", __name__, url_prefix="/catalogue")

UNITS = ["each", "unit", "visit", "hour", "day", "job", "month", "seat", "window", "room", "m2", "m", "item", "trip", "box", "floor"]


def _form_to_values(f):
    name_en = f.get("name_en", "").strip()
    name_ar = f.get("name_ar", "").strip()
    if not (name_en or name_ar):
        raise ValueError("Enter a service name in English or Arabic.")
    price_txt = f.get("price", "").strip()
    price = parse_bhd(price_txt) if price_txt else None
    tax = f.get("tax_class", "standard")
    if tax not in ("standard", "zero", "exempt"):
        tax = "standard"
    unit = f.get("unit", "each").strip()[:20] or "each"
    return (name_en or name_ar, name_ar, f.get("desc_en", "").strip()[:600], f.get("desc_ar", "").strip()[:600],
            unit, price, tax, f.get("keywords", "").strip()[:400])


@bp.route("/")
@login_required
def index():
    c = current_company()
    rows = get_db().execute("SELECT * FROM services WHERE company_id=? AND active=1 ORDER BY name_en", (c["id"],)).fetchall()
    return render_template("catalogue.html", services=rows, units=UNITS, edit=None, packs=list(STARTER_PACKS))


@bp.route("/<int:sid>/edit")
@login_required
def edit(sid):
    c = current_company()
    s = get_owned("services", sid, c["id"])
    if not s or not s["active"]:
        abort(404)
    rows = get_db().execute("SELECT * FROM services WHERE company_id=? AND active=1 ORDER BY name_en", (c["id"],)).fetchall()
    return render_template("catalogue.html", services=rows, units=UNITS, edit=s, packs=list(STARTER_PACKS))


@bp.route("/save", methods=["POST"])
@login_required
def save():
    c, u, db = current_company(), current_user(), get_db()
    sid = request.form.get("id")
    try:
        vals = _form_to_values(request.form)
    except (ValueError, MoneyError) as e:
        flash(str(e), "error")
        return redirect(url_for("catalogue.edit", sid=int(sid)) if sid else url_for("catalogue.index"))
    if sid:
        if not get_owned("services", int(sid), c["id"]):
            abort(404)
        db.execute("""UPDATE services SET name_en=?, name_ar=?, desc_en=?, desc_ar=?, unit=?, default_price_fils=?,
                      tax_class=?, keywords=? WHERE id=? AND company_id=?""", (*vals, int(sid), c["id"]))
        audit.log(c["id"], u["id"], "service", int(sid), "update", {"name": vals[0], "price_fils": vals[5]})
    else:
        cur = db.execute("""INSERT INTO services (company_id, name_en, name_ar, desc_en, desc_ar, unit,
                            default_price_fils, tax_class, keywords) VALUES (?,?,?,?,?,?,?,?,?)""", (c["id"], *vals))
        audit.log(c["id"], u["id"], "service", cur.lastrowid, "create", {"name": vals[0], "price_fils": vals[5]})
    db.commit()
    flash("Service saved.", "ok")
    return redirect(url_for("catalogue.index"))


@bp.route("/<int:sid>/delete", methods=["POST"])
@login_required
def delete(sid):
    c, u, db = current_company(), current_user(), get_db()
    if not get_owned("services", sid, c["id"]):
        abort(404)
    # soft delete so existing quotes that reference the service keep working
    db.execute("UPDATE services SET active=0 WHERE id=? AND company_id=?", (sid, c["id"]))
    audit.log(c["id"], u["id"], "service", sid, "delete")
    db.commit()
    flash("Service removed.", "ok")
    return redirect(url_for("catalogue.index"))


@bp.route("/starter/<pack>", methods=["POST"])
@login_required
def starter(pack):
    """Load a starter catalogue WITHOUT prices: the owner always sets their own."""
    if pack not in STARTER_PACKS:
        abort(404)
    c, u, db = current_company(), current_user(), get_db()
    for (en, ar, den, dar, unit, _price, tax, kw) in STARTER_PACKS[pack]:
        db.execute("""INSERT INTO services (company_id, name_en, name_ar, desc_en, desc_ar, unit,
                      default_price_fils, tax_class, keywords) VALUES (?,?,?,?,?,?,NULL,?,?)""",
                   (c["id"], en, ar, den, dar, unit, tax, kw))
    audit.log(c["id"], u["id"], "service", None, "load_starter_pack", {"pack": pack})
    db.commit()
    flash("Starter services added. Add your own prices to each service. We never guess prices.", "ok")
    return redirect(url_for("catalogue.index"))
