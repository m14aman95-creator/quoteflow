"""One combined demo account, username login, account changes."""
import pytest
import seed
from conftest import Client, register
from quoteflow.db import get_db


@pytest.fixture()
def one(app):
    assert seed.seed_all(app, "Boss", "s3cret-pass!") is True
    return app


def test_seed_all_has_every_service_and_history(one):
    with one.app_context():
        db = get_db()
        cid = db.execute("SELECT company_id FROM users WHERE username='Boss'").fetchone()["company_id"]
        names = [r["name_en"] for r in db.execute("SELECT name_en FROM services WHERE company_id=?", (cid,))]
        assert len(names) == 41
        for want in ("AC general service", "Apartment deep cleaning", "Plumbing call-out", "Local home move: 2-bedroom", "Storage (per month)"):
            assert any(n.startswith(want) for n in names), want
        assert db.execute("SELECT COUNT(*) n FROM quotes WHERE company_id=?", (cid,)).fetchone()["n"] == 18
        assert db.execute("SELECT COUNT(*) n FROM companies").fetchone()["n"] == 1
    assert seed.seed_all(one, "boss", "other-pass-123") is False      # idempotent, case-insensitive


def test_login_by_username_case_insensitive_and_wrong_password(one):
    c = Client(one)
    assert c.post("/login", {"username": "BOSS", "password": "s3cret-pass!"}, page="/login").status_code == 302
    assert "Al Noor Home Services" in c.get("/").get_data(as_text=True)
    d = Client(one)
    r = d.post("/login", {"username": "Boss", "password": "wrong"}, page="/login")
    assert r.status_code == 401 and "Incorrect username or password" in r.get_data(as_text=True)
    assert Client(one).post("/login", {"username": "nobody", "password": "x"}, page="/login").status_code == 401


def test_login_page_shows_no_demo_credentials(one):
    html = Client(one).get("/login").get_data(as_text=True)
    assert "demo1234" not in html and "@demo.qf" not in html and 'name="username"' in html


def test_register_needs_unique_valid_username(app):
    c = Client(app)
    bad = c.post("/register", {"company_name": "A", "username": "a b", "password": "password123"}, page="/register")
    assert bad.status_code == 400
    ok = c.post("/register", {"company_name": "A", "username": "alpha", "password": "password123"}, page="/register")
    assert ok.status_code == 302                                   # email is optional
    dup = Client(app).post("/register", {"company_name": "B", "username": "ALPHA", "password": "password123"}, page="/register")
    assert dup.status_code == 400


def test_change_username_and_password(one):
    c = Client(one)
    c.post("/login", {"username": "Boss", "password": "s3cret-pass!"}, page="/login")
    c.post("/account", {"username": "newboss", "password": "brand-new-pass", "current": "WRONG"}, page="/account")
    assert Client(one).post("/login", {"username": "newboss", "password": "brand-new-pass"}, page="/login").status_code == 401
    c.post("/account", {"username": "newboss", "password": "brand-new-pass", "current": "s3cret-pass!"}, page="/account")
    d = Client(one)
    assert d.post("/login", {"username": "newboss", "password": "brand-new-pass"}, page="/login").status_code == 302
    assert Client(one).post("/login", {"username": "Boss", "password": "s3cret-pass!"}, page="/login").status_code == 401


def test_legacy_email_login_still_works(app):
    seed.seed_legacy(app)
    assert Client(app).post("/login", {"email": "ac@demo.qf", "password": "demo1234"}, page="/login").status_code == 302
