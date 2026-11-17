import json
import pytest
import seed
import legacy_seed
from conftest import Client
from quoteflow.db import get_db
from quoteflow.usage import usage_summary

MSG = "Need AC service for three units in Saar tomorrow, one is leaking, send price"


@pytest.fixture()
def ac(app):
    legacy_seed.seed_legacy(app)
    c = Client(app)
    assert c.post("/login", {"email": "ac@demo.qf", "password": "demo1234"}, page="/login").status_code == 302
    return c


def make_quote(c, text=MSG):
    r = c.post("/enquiries/new", {"text": text}, page="/enquiries/new")
    eid = int(r.headers["Location"].rsplit("/", 1)[1])
    r = c.post(f"/enquiries/{eid}/create-quote", {"name": "Ahmed", "phone": "39991234", "location": "Saar"},
               page=f"/enquiries/{eid}")
    return int(r.headers["Location"].rsplit("/", 1)[1])


def form_from_db(app, qid, **over):
    """Build the editor form the browser would post, from the current DB state."""
    with app.app_context():
        db = get_db()
        items = [dict(r) for r in db.execute("SELECT * FROM quote_items WHERE quote_id=? ORDER BY position", (qid,))]
        q = dict(db.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone())
    f = {"item_count": str(len(items)), "language": "both", "valid_until": q["valid_until"], "discount_type": "none",
         "discount_value": "", "terms_en": "t", "terms_ar": "ش", "notes": "", "cust_name": "Ahmed",
         "cust_phone": "39991234", "cust_location": "Saar", "action": "save"}
    for i, it in enumerate(items):
        f.update({f"item_id_{i}": it["id"], f"service_id_{i}": it["service_id"] or "", f"title_en_{i}": it["title_en"],
                  f"title_ar_{i}": it["title_ar"], f"desc_en_{i}": it["desc_en"], f"desc_ar_{i}": it["desc_ar"],
                  f"qty_{i}": str(it["quantity_milli"] / 1000).rstrip("0").rstrip("."),
                  f"price_{i}": "" if it["unit_price_fils"] is None else f"{it['unit_price_fils'] / 1000:.3f}",
                  f"tax_{i}": it["tax_class"], f"unit_{i}": it["unit"], f"origin_{i}": it["origin"],
                  f"uncertain_{i}": "0", f"reviewed_{i}": "1", f"customer_words_{i}": it["customer_words"]})
    f.update(over)
    return f


def q_row(app, qid):
    with app.app_context():
        return dict(get_db().execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone())


def test_draft_from_enquiry_uses_catalogue_prices_and_code_totals(app, ac):
    qid = make_quote(ac)
    q = q_row(app, qid)
    assert q["status"] == "draft" and q["number"].startswith("Q-")
    assert (q["subtotal_fils"], q["vat_fils"], q["total_fils"]) == (54000, 5400, 59400)
    with app.app_context():
        assert usage_summary(dict(get_db().execute("SELECT * FROM companies WHERE id=1").fetchone()))["used"] == 1


def test_create_quote_is_idempotent(app, ac):
    r = ac.post("/enquiries/new", {"text": MSG}, page="/enquiries/new")
    eid = r.headers["Location"].rsplit("/", 1)[1]
    a = ac.post(f"/enquiries/{eid}/create-quote", {"name": "A"}, page=f"/enquiries/{eid}").headers["Location"]
    b = ac.post(f"/enquiries/{eid}/create-quote", {"name": "A"}, page=f"/enquiries/{eid}").headers["Location"]
    assert a == b
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) n FROM quotes WHERE enquiry_id=?", (eid,)).fetchone()["n"] == 1


def test_unpriced_items_block_approval_and_ai_never_priced(app, ac):
    # unknown service: no catalogue match, so no price may appear
    qid = make_quote(ac, "Please quote for installing a water heater in Seef tomorrow")
    with app.app_context():
        for it in get_db().execute("SELECT * FROM quote_items WHERE quote_id=?", (qid,)):
            assert it["unit_price_fils"] is None and it["price_source"] == "none"
    r = ac.post(f"/quotes/{qid}/save", form_from_db(app, qid, action="approve"), page=f"/quotes/{qid}")
    assert r.status_code == 302
    assert q_row(app, qid)["approved_at"] is None  # blocked: no price
    page = ac.get(f"/quotes/{qid}").get_data(as_text=True)
    assert "enter a price" in page


def test_edit_price_audit_and_approve_flow(app, ac):
    qid = make_quote(ac)
    f = form_from_db(app, qid, price_0="15.500")
    ac.post(f"/quotes/{qid}/save", f, page=f"/quotes/{qid}")
    q = q_row(app, qid)
    assert q["subtotal_fils"] == 3 * 15500 + 18000 and q["total_fils"] == q["subtotal_fils"] + q["vat_fils"]
    with app.app_context():
        it = get_db().execute("SELECT * FROM quote_items WHERE quote_id=? ORDER BY position", (qid,)).fetchone()
        assert it["price_source"] == "manual"
        detail = get_db().execute("SELECT detail FROM audit_log WHERE entity='quote' AND action='edit' ORDER BY id DESC").fetchone()["detail"]
        assert "12.000 -> 15.500" in detail
    # approve
    ac.post(f"/quotes/{qid}/save", form_from_db(app, qid, price_0="15.500", action="approve"), page=f"/quotes/{qid}")
    q = q_row(app, qid)
    assert q["approved_at"] and q["approved_by"]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) n FROM audit_log WHERE action='approve'").fetchone()["n"] == 1
    # locked: editing is refused until unlocked; unlock clears approval
    ac.post(f"/quotes/{qid}/save", form_from_db(app, qid, price_0="1.000"), page=f"/quotes/{qid}")
    assert q_row(app, qid)["total_fils"] == q["total_fils"]
    ac.post(f"/quotes/{qid}/unlock", page=f"/quotes/{qid}")
    assert q_row(app, qid)["approved_at"] is None


def test_unreviewed_item_blocks_approval(app, ac):
    qid = make_quote(ac)
    f = form_from_db(app, qid, action="approve")
    f.pop("reviewed_1")
    ac.post(f"/quotes/{qid}/save", f, page=f"/quotes/{qid}")
    assert q_row(app, qid)["approved_at"] is None


def test_vat_exempt_and_discount_in_save(app, ac):
    qid = make_quote(ac)
    f = form_from_db(app, qid, discount_type="percent", discount_value="10", tax_1="zero")
    ac.post(f"/quotes/{qid}/save", f, page=f"/quotes/{qid}")
    q = q_row(app, qid)
    # subtotal 54.000, 10% = 5.400; taxable share: line1 36.000 - 3.600 = 32.400 -> VAT 3.240
    assert (q["subtotal_fils"], q["discount_fils"], q["vat_fils"], q["total_fils"]) == (54000, 5400, 3240, 51840)


@pytest.mark.parametrize("bad", ["12.5555", "abc", "-5"])
def test_bad_price_rejected_not_saved(app, ac, bad):
    qid = make_quote(ac)
    ac.post(f"/quotes/{qid}/save", form_from_db(app, qid, price_0=bad), page=f"/quotes/{qid}")
    assert q_row(app, qid)["subtotal_fils"] == 54000


def test_add_remove_items(app, ac):
    qid = make_quote(ac)
    f = form_from_db(app, qid)
    f.update({"item_count": "3", "item_id_2": "", "service_id_2": "", "title_en_2": "Custom part", "title_ar_2": "",
              "desc_en_2": "", "desc_ar_2": "", "qty_2": "2", "price_2": "5.250", "tax_2": "standard", "unit_2": "each",
              "origin_2": "manual", "uncertain_2": "0", "reviewed_2": "1", "customer_words_2": "", "delete_1": "1"})
    ac.post(f"/quotes/{qid}/save", f, page=f"/quotes/{qid}")
    assert q_row(app, qid)["subtotal_fils"] == 36000 + 10500


def test_feedback_and_status_rules(app, ac):
    qid = make_quote(ac)
    ac.post(f"/quotes/{qid}/status", {"status": "sent"}, page=f"/quotes/{qid}")
    assert q_row(app, qid)["status"] == "draft"                      # cannot send before approval
    ac.post(f"/quotes/{qid}/save", form_from_db(app, qid, action="approve"), page=f"/quotes/{qid}")
    ac.post(f"/quotes/{qid}/status", {"status": "sent"}, page=f"/quotes/{qid}")
    q = q_row(app, qid)
    assert q["status"] == "sent" and q["sent_at"]
    ac.post(f"/quotes/{qid}/feedback", {"rating": "minor"}, page=f"/quotes/{qid}")
    ac.post(f"/quotes/{qid}/feedback", {"rating": "nonsense"}, page=f"/quotes/{qid}")
    assert q_row(app, qid)["feedback"] == "minor"
    assert ac.post(f"/quotes/{qid}/status", {"status": "bogus"}, page=f"/quotes/{qid}").status_code == 400


def test_live_totals_endpoint_uses_server_engine(app, ac):
    tok = ac.token("/")
    r = ac.c.post("/quotes/totals", json={"items": [{"qty": "3", "price": "12.000", "tax": "standard"},
                                                  {"qty": "1", "price": "", "tax": "standard"}],
                                         "discount_type": "none", "discount_value": ""},
                  headers={"X-CSRF-Token": tok})
    j = r.get_json()
    assert j["subtotal"] == "36.000" and j["vat"] == "3.600" and j["total"] == "39.600" and j["complete"] is False
    bad = ac.c.post("/quotes/totals", json={"items": [{"qty": "x", "price": "1"}]}, headers={"X-CSRF-Token": tok})
    assert "error" in bad.get_json()
    assert ac.c.post("/quotes/totals", json={"items": []}).status_code == 400  # CSRF enforced


def test_free_plan_limit_blocks_6th_quote(app):
    legacy_seed.seed_legacy(app)
    c = Client(app)
    c.post("/login", {"email": "clean@demo.qf", "password": "demo1234"}, page="/login")   # Free: 5/month
    for _ in range(5):
        make_quote(c, "Need apartment deep cleaning in Seef tomorrow, 2 bedrooms")
    r = c.post("/enquiries/new", {"text": "Need apartment deep cleaning in Seef"}, page="/enquiries/new")
    assert r.status_code == 403
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) n FROM quotes WHERE enquiry_id IS NOT NULL").fetchone()["n"] == 5


def test_tenant_isolation_on_quotes_and_enquiries(app):
    legacy_seed.seed_legacy(app)
    a, b = Client(app), Client(app)
    a.post("/login", {"email": "ac@demo.qf", "password": "demo1234"}, page="/login")
    b.post("/login", {"email": "clean@demo.qf", "password": "demo1234"}, page="/login")
    qid = make_quote(a)
    assert b.get(f"/quotes/{qid}").status_code == 404
    assert b.post(f"/quotes/{qid}/save", form_from_db(app, qid), page="/").status_code == 404
    assert b.post(f"/quotes/{qid}/unlock", page="/").status_code == 404
    assert b.post(f"/quotes/{qid}/status", {"status": "sent"}, page="/").status_code == 404
    assert b.post(f"/quotes/{qid}/feedback", {"rating": "minor"}, page="/").status_code == 404
    assert b.get("/enquiries/1").status_code == 404
    assert b.get("/enquiries/1/whatsapp-text").status_code == 404
    assert b.post("/enquiries/1/create-quote", {}, page="/").status_code == 404


def test_whatsapp_clarification_text(app, ac):
    r = ac.post("/enquiries/new", {"text": "Need AC service"}, page="/enquiries/new")
    eid = r.headers["Location"].rsplit("/", 1)[1]
    j = ac.get(f"/enquiries/{eid}/whatsapp-text?lang=both&q=0&q=1").get_json()
    assert "1." in j["text"] and "2." in j["text"] and "السلام عليكم" in j["text"] and "Hello" in j["text"]
    page = ac.get(f"/enquiries/{eid}").get_data(as_text=True)
    assert "Missing details" in page and "Copy message" in page


def test_enquiry_text_never_rendered_unescaped(app, ac):
    r = ac.post("/enquiries/new", {"text": "AC service <script>alert(1)</script> 2 units Saar"}, page="/enquiries/new")
    page = ac.get(r.headers["Location"]).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
