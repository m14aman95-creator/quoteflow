"""Email problems must never crash sign-up, and the account-type chooser must work."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from conftest import Client
from quoteflow import mailer, verify as vf
from test_portal import owner, join, SLUG  # noqa: F401


def test_nbsp_in_smtp_password_does_not_crash_signup(app, owner):
    app.config.update(SMTP_HOST="127.0.0.1", SMTP_PORT=1, SMTP_USER="u@test", SMTP_PASSWORD="ab\xa0cd")
    join(app, phone="3999 1111", name="Sara", email="sara@example.com")      # join() asserts a normal redirect, not a 500


def test_send_notice_never_raises(app):
    app.config.update(SMTP_HOST="127.0.0.1", SMTP_PORT=1, SMTP_USER="u", SMTP_PASSWORD="bad\xa0pw")
    assert mailer.send_notice(app.config, to="a@b.co", subject="s", body="b") is False


def test_config_cleans_pasted_values(monkeypatch):
    import importlib, quoteflow.config as c
    monkeypatch.setenv("SMTP_PORT", "")
    monkeypatch.setenv("SMTP_PASSWORD", "ab\xa0cd ef")
    importlib.reload(c)
    assert c.Config.SMTP_PORT == 587 and c.Config.SMTP_PASSWORD == "abcdef"


class _Brevo(BaseHTTPRequestHandler):
    seen = []
    status = 201

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _Brevo.seen.append((self.headers.get("api-key"), body))
        self.send_response(_Brevo.status); self.send_header("content-type", "application/json"); self.end_headers()
        self.wfile.write(b'{"messageId":"x"}' if _Brevo.status < 300 else b'{"message":"Key not found"}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def brevo(app):
    srv = HTTPServer(("127.0.0.1", 0), _Brevo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Brevo.seen.clear(); _Brevo.status = 201
    app.config.update(BREVO_API_KEY="k123", MAIL_FROM="me@shop.bh", BREVO_API_URL=f"http://127.0.0.1:{srv.server_port}/v3/smtp/email")
    yield app
    srv.shutdown()


def test_brevo_api_sends_with_pdf(brevo):
    assert mailer.mail_enabled(brevo.config) and mailer.method(brevo.config) == "api"
    mailer.send_quote_email(brevo.config, to="c@x.com", company_name="Shop", reply_to="r@x.com", subject="Quote", body="hi",
                            pdf_bytes=b"%PDF-1", pdf_name="q.pdf")
    key, body = _Brevo.seen[-1]
    assert key == "k123" and body["to"] == [{"email": "c@x.com"}] and body["attachment"][0]["name"] == "q.pdf"


def test_brevo_error_is_readable(brevo):
    _Brevo.status = 401
    ok, msg = mailer.send_test(brevo.config, "me@x.com")
    assert not ok and "Brevo refused" in msg and "k123" not in msg


def test_signup_sends_code_through_api(brevo, owner):
    join(brevo, phone="3999 1111", name="Sara", email="sara@example.com")
    assert any("sara@example.com" in b["to"][0]["email"] for _, b in _Brevo.seen)


def test_owner_test_email_button_and_toggle(brevo, owner):
    r = owner.post("/portal/test-email", {"to": "me@x.com"}, page="/portal")
    assert "Test email sent" in owner.get("/portal").get_data(as_text=True) or r.status_code in (200, 302)
    assert _Brevo.seen
    owner.post("/portal", {"slug": SLUG, "enabled": "1"}, page="/portal")      # verify box left off
    with brevo.app_context():
        from quoteflow.db import get_db
        co = get_db().execute("SELECT * FROM companies WHERE slug=?", (SLUG,)).fetchone()
        assert not vf.active(co)


def test_unhandled_error_shows_reference_not_traceback(app):
    @app.route("/boom")
    def boom():
        raise RuntimeError("secret detail")
    app.config["TESTING"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    r = app.test_client().get("/boom")
    t = r.get_data(as_text=True)
    assert r.status_code == 500 and "Something went wrong" in t and "secret detail" not in t


def test_chooser_pages(app, owner):
    c = app.test_client()
    html = c.get("/start").get_data(as_text=True)
    assert "I run a business" in html and "I am a customer" in html
    assert "I am a customer" in c.get("/login").get_data(as_text=True)
    r = c.get("/find")                                    # one enabled portal -> straight to it
    assert r.status_code == 302 and f"/c/{SLUG}/" in r.headers["Location"]


def test_find_by_pasted_link_and_unknown(app, owner):
    cl = Client(app)
    r = cl.post("/find", {"q": f"https://x.onrender.com/c/{SLUG}/"}, page="/login")
    assert r.status_code == 302 and f"/c/{SLUG}/" in r.headers["Location"]
    r = cl.post("/find", {"q": "nope-nope"}, page="/login")
    assert r.status_code == 404 and "could not find" in r.get_data(as_text=True)
