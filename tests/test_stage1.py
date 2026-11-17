from conftest import register
from quoteflow.db import get_db
from quoteflow.usage import usage_summary, record_quote_created, can_create_quote


def test_register_login_logout(client):
    r = register(client)
    assert r.status_code == 302 and "/onboarding" in r.headers["Location"]
    assert client.get("/").status_code == 200
    client.post("/logout", page="/")
    assert client.get("/").status_code == 302  # redirected to login


def test_bad_login_rejected(client):
    register(client)
    client.post("/logout", page="/")
    r = client.post("/login", {"email": "owner@a.qf", "password": "wrongwrong"}, page="/login")
    assert r.status_code == 401


def test_csrf_required(client):
    r = client.c.post("/register", data={"company_name": "X", "email": "x@x.qf", "password": "password123"})
    assert r.status_code == 400


def test_password_min_length(client):
    r = register(client, pw="short")
    assert r.status_code == 400


def test_settings_require_vat_confirmation_and_number(client):
    register(client)
    base = {"name_en": "Alpha", "vat_registered": "yes", "vat_number": "", "vat_rate": "10",
            "validity_days": "14", "retention_days": "30", "preferred_lang": "en", "vat_confirm": "1"}
    assert client.post("/settings", base, page="/settings").status_code == 400  # VAT registered but no number
    base["vat_number"] = "220012345600002"
    base.pop("vat_confirm")
    assert client.post("/settings", base, page="/settings").status_code == 400  # not confirmed
    base["vat_confirm"] = "1"
    r = client.post("/settings", base, page="/settings")
    assert r.status_code == 302


def test_settings_saved_and_audited(app, client):
    register(client)
    client.post("/settings", {"name_en": "Alpha", "vat_registered": "no", "vat_rate": "5", "validity_days": "21",
                              "retention_days": "7", "preferred_lang": "both", "vat_confirm": "1"}, page="/settings")
    with app.app_context():
        db = get_db()
        c = db.execute("SELECT * FROM companies").fetchone()
        assert c["vat_rate_bp"] == 500 and c["validity_days"] == 21 and c["preferred_lang"] == "both"
        assert c["vat_confirmed_at"]
        n = db.execute("SELECT COUNT(*) n FROM audit_log WHERE action='update_settings'").fetchone()["n"]
        assert n == 1


def test_free_plan_limit_enforced(app, client):
    register(client)
    with app.app_context():
        db = get_db()
        c = dict(db.execute("SELECT * FROM companies").fetchone())
        for _ in range(5):
            assert can_create_quote(c)
            record_quote_created(c["id"])
        db.commit()
        assert not can_create_quote(c)
        assert usage_summary(c)["limit"] == 5
        db.execute("UPDATE companies SET plan='starter' WHERE id=?", (c["id"],))
        c["plan"] = "starter"
        assert can_create_quote(c) and usage_summary(c)["limit"] == 30


def test_plan_limits_match_spec():
    from quoteflow.plans import PLANS
    assert [PLANS[k]["quotes_per_month"] for k in ("free", "starter", "professional", "business")] == [5, 30, 150, 500]


def test_audit_page_tenant_scoped(two_clients):
    a, b = two_clients
    a.post("/settings", {"name_en": "Alpha SECRETNAME", "vat_registered": "no", "vat_rate": "10",
                         "validity_days": "14", "retention_days": "30", "preferred_lang": "en", "vat_confirm": "1"},
           page="/settings")
    page_b = b.get("/audit").get_data(as_text=True)
    assert "SECRETNAME" not in page_b


def test_retention_purge(app, client):
    register(client)
    from quoteflow.retention import purge_expired
    with app.app_context():
        db = get_db()
        cid = db.execute("SELECT id FROM companies").fetchone()["id"]
        db.execute("INSERT INTO enquiries (company_id, raw_text, purge_after) VALUES (?,?,?)",
                   (cid, "old text", "2000-01-01 00:00:00"))
        db.execute("INSERT INTO enquiries (company_id, raw_text, purge_after) VALUES (?,?,?)",
                   (cid, "fresh text", "2999-01-01 00:00:00"))
        db.commit()
        assert purge_expired() == 1
        rows = [r["raw_text"] for r in db.execute("SELECT raw_text FROM enquiries ORDER BY id")]
        assert rows == [None, "fresh text"]
