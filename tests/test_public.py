"""Interactive customer link: only approved quotes, server-side totals, optional add-ons, accept/decline, privacy."""
import re
import pytest
from conftest import Client, register
from quoteflow.db import get_db
from test_quotes import ac, make_quote, form_from_db, q_row  # noqa: F401


def approved_with_optional(app, ac, optional_index=1):
    qid = make_quote(ac)
    f = form_from_db(app, qid, price_0="15.500", price_1="18.000", action="approve")
    f[f"optional_{optional_index}"] = "1"
    ac.post(f"/quotes/{qid}/save", f, page=f"/quotes/{qid}")
    assert q_row(app, qid)["approved_at"]
    return qid


def make_link(ac, qid):
    ac.post(f"/quotes/{qid}/link", {}, page=f"/quotes/{qid}")
    html = ac.get(f"/quotes/{qid}/share").get_data(as_text=True)
    return re.search(r'/q/([A-Za-z0-9_\-]+)', html).group(1)


def item_ids(app, qid):
    with app.app_context():
        return [r["id"] for r in get_db().execute("SELECT id FROM quote_items WHERE quote_id=? ORDER BY position", (qid,))]


def test_link_requires_approval(app, ac):
    qid = make_quote(ac)
    ac.post(f"/quotes/{qid}/link", {}, page=f"/quotes/{qid}")
    assert q_row(app, qid)["share_token"] is None


def test_optional_item_excluded_from_base_total(app, ac):
    qid = approved_with_optional(app, ac)
    q = q_row(app, qid)
    # item 0: 3 x 15.500 = 46.500 ; item 1 (1 x 18.000) is optional -> not in the base
    assert q["subtotal_fils"] == 46500
    assert q["total_fils"] == 46500 + 4650


def test_public_page_unknown_and_unapproved_are_404(app, ac):
    anon = Client(app)
    assert anon.get("/q/" + "x" * 32).status_code == 404
    qid = make_quote(ac)
    with app.app_context():
        db = get_db(); db.execute("UPDATE quotes SET share_token='unapprovedtoken1234567890abc' WHERE id=?", (qid,)); db.commit()
    assert anon.get("/q/unapprovedtoken1234567890abc").status_code == 404


def test_public_view_totals_and_accept(app, ac):
    qid = approved_with_optional(app, ac)
    tok = make_link(ac, qid)
    anon = Client(app)
    r = anon.get(f"/q/{tok}")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Optional add-ons" in html and "no-referrer" == r.headers["Referrer-Policy"]
    assert q_row(app, qid)["view_count"] == 1
    ids = item_ids(app, qid)
    # server recalculates with the optional item chosen: 46.500 + 18.000 = 64.500 + 10% VAT = 70.950
    anon.token(f"/q/{tok}")
    rr = anon.c.post(f"/q/{tok}/totals", json={"selected": [ids[1]]}, headers={"X-CSRF-Token": anon.token(f"/q/{tok}")})
    j = rr.get_json()
    assert j["subtotal"] == "64.500" and j["total"] == "70.950"
    # ids that are not optional / not in this quote are ignored
    j2 = anon.c.post(f"/q/{tok}/totals", json={"selected": [ids[0], 99999]}, headers={"X-CSRF-Token": anon.token(f"/q/{tok}")}).get_json()
    assert j2["total"] == "51.150"
    # accept needs a name and the box
    anon.post(f"/q/{tok}/accept", {"name": "", "agree": "1", "opt": str(ids[1])}, page=f"/q/{tok}")
    assert q_row(app, qid)["status"] != "accepted"
    anon.post(f"/q/{tok}/accept", {"name": "Ahmed Ali", "agree": "1", "opt": str(ids[1])}, page=f"/q/{tok}")
    q = q_row(app, qid)
    assert q["status"] == "accepted" and q["response_name"] == "Ahmed Ali" and q["total_fils"] == 70950
    assert q["selected_optional"] == str(ids[1])
    # a second response is ignored (cannot be flipped after the fact)
    anon.post(f"/q/{tok}/decline", {"reason": "changed my mind"}, page=f"/q/{tok}")
    assert q_row(app, qid)["status"] == "accepted"
    with app.app_context():
        acts = {r["action"] for r in get_db().execute("SELECT action FROM audit_log")}
    assert {"customer_viewed", "customer_accepted", "link_created"} <= acts


def test_decline_and_owner_preview_not_counted(app, ac):
    qid = approved_with_optional(app, ac)
    tok = make_link(ac, qid)
    ac.get(f"/q/{tok}")                         # owner previewing: not a customer view
    assert q_row(app, qid)["view_count"] == 0
    anon = Client(app)
    anon.post(f"/q/{tok}/decline", {"reason": "too expensive"}, page=f"/q/{tok}")
    q = q_row(app, qid)
    assert q["status"] == "rejected" and q["response_note"] == "too expensive"


def test_expired_quote_cannot_be_accepted(app, ac):
    qid = approved_with_optional(app, ac)
    tok = make_link(ac, qid)
    with app.app_context():
        db = get_db(); db.execute("UPDATE quotes SET valid_until='2020-01-01' WHERE id=?", (qid,)); db.commit()
    anon = Client(app)
    assert "expired" in anon.get(f"/q/{tok}").get_data(as_text=True).lower()
    anon.post(f"/q/{tok}/accept", {"name": "X Y", "agree": "1"}, page=f"/q/{tok}")
    assert q_row(app, qid)["status"] != "accepted"


def test_revoke_link_and_edit_disables_it(app, ac):
    qid = approved_with_optional(app, ac)
    tok = make_link(ac, qid)
    anon = Client(app)
    assert anon.get(f"/q/{tok}").status_code == 200
    ac.post(f"/quotes/{qid}/link/revoke", {}, page=f"/quotes/{qid}")
    assert anon.get(f"/q/{tok}").status_code == 404
    tok2 = make_link(ac, qid)
    assert tok2 != tok
    # editing the quote withdraws approval, so the link stops working until re-approved
    ac.post(f"/quotes/{qid}/unlock", {}, page=f"/quotes/{qid}")
    ac.post(f"/quotes/{qid}/save", form_from_db(app, qid, price_0="16.000"), page=f"/quotes/{qid}")
    assert anon.get(f"/q/{tok2}").status_code == 404


def test_cross_tenant_cannot_create_or_revoke_link(app, ac):
    qid = approved_with_optional(app, ac)
    other = Client(app); register(other, "x@x.qf", "Other Co")
    assert other.post(f"/quotes/{qid}/link", {}, page="/settings").status_code in (403, 404)
    assert q_row(app, qid)["share_token"] is None


def test_pdf_includes_chosen_optional_and_lists_others(app, ac, monkeypatch):
    from quoteflow import docs
    qid = approved_with_optional(app, ac)
    tok = make_link(ac, qid)
    seen = {}
    monkeypatch.setattr(docs, "html_to_pdf", lambda html, timeout=45: seen.setdefault("html", html).encode()[:10] or b"%PDF")
    anon = Client(app)
    anon.get(f"/q/{tok}/pdf")
    assert "Optional add-ons" in seen["html"] and "Not included" in seen["html"]
    ids = item_ids(app, qid)
    seen.clear()
    anon.get(f"/q/{tok}/pdf?sel={ids[1]}")
    assert "Optional add-ons" not in seen["html"] and "Selected by the customer" in seen["html"]
