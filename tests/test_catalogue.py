import re
from conftest import Client, register
from quoteflow.db import get_db


def _svc(name="Test svc", price="12.500", tax="standard"):
    return {"name_en": name, "name_ar": "خدمة", "desc_en": "d", "desc_ar": "و", "unit": "unit",
            "price": price, "tax_class": tax, "keywords": "a,b"}


def test_create_edit_delete_service_with_audit(app, client):
    register(client)
    assert client.post("/catalogue/save", _svc(), page="/catalogue/").status_code == 302
    with app.app_context():
        s = get_db().execute("SELECT * FROM services").fetchone()
        assert s["default_price_fils"] == 12500 and s["tax_class"] == "standard"
        sid = s["id"]
    d = _svc("Renamed", price="")
    d["id"] = sid
    client.post("/catalogue/save", d, page="/catalogue/")
    client.post(f"/catalogue/{sid}/delete", page="/catalogue/")
    with app.app_context():
        db = get_db()
        s = db.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
        assert s["name_en"] == "Renamed" and s["default_price_fils"] is None and s["active"] == 0
        acts = [r["action"] for r in db.execute("SELECT action FROM audit_log WHERE entity='service' ORDER BY id")]
        assert acts == ["create", "update", "delete"]


def test_invalid_price_rejected(app, client):
    register(client)
    client.post("/catalogue/save", _svc(price="12.3456"), page="/catalogue/")
    client.post("/catalogue/save", _svc(price="abc"), page="/catalogue/")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) n FROM services").fetchone()["n"] == 0


def test_starter_pack_has_no_prices(app, client):
    register(client)
    client.post("/catalogue/starter/ac", page="/catalogue/")
    with app.app_context():
        rows = get_db().execute("SELECT default_price_fils FROM services").fetchall()
        assert len(rows) >= 5 and all(r["default_price_fils"] is None for r in rows)


def test_tenant_isolation_services(app, two_clients):
    a, b = two_clients
    a.post("/catalogue/save", _svc("AlphaOnly"), page="/catalogue/")
    with app.app_context():
        sid = get_db().execute("SELECT id FROM services").fetchone()["id"]
    # B cannot see, edit, or delete A's service
    assert "AlphaOnly" not in b.get("/catalogue/").get_data(as_text=True)
    assert b.get(f"/catalogue/{sid}/edit").status_code == 404
    assert b.post(f"/catalogue/{sid}/delete", page="/catalogue/").status_code == 404
    d = _svc("Hijack"); d["id"] = sid
    assert b.post("/catalogue/save", d, page="/catalogue/").status_code == 404
    with app.app_context():
        s = get_db().execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
        assert s["name_en"] == "AlphaOnly" and s["active"] == 1


def test_seed_creates_demo_companies(app):
    import seed
    import legacy_seed
    made = legacy_seed.seed_legacy(app)
    assert set(made) == {"ac@demo.qf", "clean@demo.qf", "home@demo.qf"}
    c = Client(app)
    r = c.post("/login", {"email": "ac@demo.qf", "password": "demo1234"}, page="/login")
    assert r.status_code == 302
    html = c.get("/catalogue/").get_data(as_text=True)
    assert "AC general service" in html and "CoolBreeze" in c.get("/").get_data(as_text=True)
    assert legacy_seed.seed_legacy(app) == []  # idempotent
