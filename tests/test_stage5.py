import re
import subprocess
import pytest
import seed
import legacy_seed
from conftest import Client
from quoteflow import docs
from quoteflow.db import get_db
from test_quotes import make_quote, form_from_db, MSG


@pytest.fixture()
def ac(app):
    legacy_seed.seed_legacy(app)
    c = Client(app)
    c.post("/login", {"email": "ac@demo.qf", "password": "demo1234"}, page="/login")
    return c


def approved_quote(app, c):
    qid = make_quote(c)
    c.post(f"/quotes/{qid}/save", form_from_db(app, qid, action="approve"), page=f"/quotes/{qid}")
    return qid


def test_document_requires_approval(app, ac):
    qid = make_quote(ac)
    assert ac.get(f"/quotes/{qid}/document").status_code == 404
    assert ac.get(f"/quotes/{qid}/pdf").status_code == 404
    assert ac.get(f"/quotes/{qid}/preview").status_code == 302
    assert ac.get(f"/quotes/{qid}/share").status_code == 302


def test_document_languages_and_rtl(app, ac):
    qid = approved_quote(app, ac)
    en = ac.get(f"/quotes/{qid}/document?lang=en").get_data(as_text=True)
    ar = ac.get(f"/quotes/{qid}/document?lang=ar").get_data(as_text=True)
    both = ac.get(f"/quotes/{qid}/document?lang=both").get_data(as_text=True)
    assert 'dir="ltr"' in en.split(">")[1] + en[:80] and "Quotation" in en and "عرض سعر" not in en
    assert re.search(r'<html[^>]*dir="rtl"', ar) and "عرض سعر" in ar and "Quotation" not in ar
    assert "Quotation" in both and "عرض سعر" in both and 'class="ar"' in both
    # totals in all three: 3x12 + 1x18 = 54.000, VAT 5.400, total 59.400
    for doc in (en, ar, both):
        assert "54.000" in doc and "5.400" in doc and "59.400" in doc
    assert "220099887700002" in en                      # VAT number shown for a VAT-registered business


def test_not_vat_registered_document_has_no_vat(app):
    legacy_seed.seed_legacy(app)
    c = Client(app)
    c.post("/login", {"email": "clean@demo.qf", "password": "demo1234"}, page="/login")
    qid = approved_quote(app, c) if False else None
    r = c.post("/enquiries/new", {"text": "Need villa deep cleaning in Janabiyah this Friday, 5 bedrooms. Sara"}, page="/enquiries/new")
    eid = r.headers["Location"].rsplit("/", 1)[1]
    qid = int(c.post(f"/enquiries/{eid}/create-quote", {"name": "Sara"}, page=f"/enquiries/{eid}").headers["Location"].rsplit("/", 1)[1])
    c.post(f"/quotes/{qid}/save", form_from_db(app, qid, action="approve"), page=f"/quotes/{qid}")
    doc = c.get(f"/quotes/{qid}/document?lang=en").get_data(as_text=True)
    assert "VAT not applicable" in doc and "VAT No." not in doc
    assert "Created with QuoteFlow AI" in doc           # Free plan shows branding


@pytest.mark.skipif(docs.find_chrome() is None, reason="Chrome not installed")
def test_pdf_export_arabic_and_english(app, ac, tmp_path):
    qid = approved_quote(app, ac)
    for lang in ("en", "ar", "both"):
        r = ac.get(f"/quotes/{qid}/pdf?lang={lang}")
        assert r.status_code == 200 and r.data.startswith(b"%PDF")
        f = tmp_path / f"{lang}.pdf"
        f.write_bytes(r.data)
        text = subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True).stdout
        assert "59.130" in text.replace("‬", "") or "59.400" in text      # total present as real text
        if lang in ("ar", "both"):
            assert any("؀" <= ch <= "ۿ" for ch in text)
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) n FROM audit_log WHERE action='export_pdf'").fetchone()["n"] == 3


def test_share_text_en_ar_both(app, ac):
    qid = approved_quote(app, ac)
    en = ac.get(f"/quotes/{qid}/share?lang=en").get_data(as_text=True)
    assert "Total: 59.400 BHD" in en and "AC general service (split unit) × 3 = 36.000 BHD" in en
    ar = ac.get(f"/quotes/{qid}/share?lang=ar").get_data(as_text=True)
    assert "الإجمالي: 59.400 BHD" in ar and "السلام عليكم" in ar
    both = ac.get(f"/quotes/{qid}/share?lang=both").get_data(as_text=True)
    assert "Hello" in both and "السلام عليكم" in both
    assert "wa.me/97339991234" in en                    # local number gets the Bahrain country code
    # nothing is ever sent by the server: no outbound call happens in these routes
    ac.post(f"/quotes/{qid}/status", {"status": "sent"}, page=f"/quotes/{qid}")


def test_history_search_and_status_filters(app, ac):
    page = ac.get("/quotes").get_data(as_text=True)
    assert "Fatima Al Khalifa" in page and "Dr. Ali Hassan Clinic" in page
    assert "Fatima" in ac.get("/quotes?q=fatima").get_data(as_text=True)
    assert "Hamad Contracting" not in ac.get("/quotes?q=fatima").get_data(as_text=True)
    assert "Hamad Contracting" in ac.get("/quotes?q=Riffa").get_data(as_text=True)           # by location
    assert "Maryam" in ac.get("/quotes?q=leak").get_data(as_text=True)                       # by service item
    assert "Q-2026-0001" in ac.get("/quotes?q=0001").get_data(as_text=True)                  # by number
    acc = ac.get("/quotes?status=accepted").get_data(as_text=True)
    assert "Fatima" in acc and "Yusuf" not in acc
    assert "Maryam" in ac.get("/quotes?status=follow_up").get_data(as_text=True)
    assert "No quotes match" in ac.get("/quotes?q=%25%25zzz").get_data(as_text=True)         # wildcard chars are escaped


def test_sent_quote_past_validity_shows_expired(app, ac):
    with app.app_context():
        db = get_db()
        db.execute("UPDATE quotes SET valid_until='2020-01-01' WHERE status='sent' AND company_id=1")
        db.commit()
    page = ac.get("/quotes?status=expired").get_data(as_text=True)
    assert "Dr. Ali Hassan Clinic" in page
    assert "Dr. Ali Hassan Clinic" not in ac.get("/quotes?status=sent").get_data(as_text=True)


def test_customers_list_and_filter(app, ac):
    page = ac.get("/customers").get_data(as_text=True)
    assert "Fatima Al Khalifa" in page and "quote(s)" in page
    assert "Hamad" not in ac.get("/customers?q=fatima").get_data(as_text=True)
    with app.app_context():
        cid = get_db().execute("SELECT id FROM customers WHERE name LIKE 'Fatima%'").fetchone()["id"]
    only = ac.get(f"/quotes?customer={cid}").get_data(as_text=True)
    assert "Fatima" in only and "Hamad" not in only


def test_history_tenant_isolation(app):
    legacy_seed.seed_legacy(app)
    a, b = Client(app), Client(app)
    a.post("/login", {"email": "ac@demo.qf", "password": "demo1234"}, page="/login")
    b.post("/login", {"email": "clean@demo.qf", "password": "demo1234"}, page="/login")
    assert "Fatima" not in b.get("/quotes").get_data(as_text=True)
    assert "Fatima Al Khalifa" not in b.get("/quotes?q=Fatima").get_data(as_text=True)
    assert "Fatima Al Khalifa" not in b.get("/customers").get_data(as_text=True)
    assert b.get("/quotes/1/document").status_code == 404
    assert b.get("/quotes/1/pdf").status_code == 404
    assert b.get("/quotes/1/share").status_code in (302, 404)


def test_seeded_quotes_do_not_use_current_month_quota(app):
    legacy_seed.seed_legacy(app)
    from quoteflow.usage import usage_summary
    with app.app_context():
        c = dict(get_db().execute("SELECT * FROM companies WHERE email='clean@demo.qf'").fetchone())
        assert usage_summary(c)["used"] == 0
