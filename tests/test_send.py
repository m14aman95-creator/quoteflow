"""Sending: only after approval, validated address, email carries the PDF, WhatsApp marks Sent."""
import smtplib
import pytest
from quoteflow import mailer, docs
from quoteflow.db import get_db
from test_quotes import ac, make_quote, form_from_db, q_row  # noqa: F401


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, **k): pass
    def login(self, u, p): pass
    def send_message(self, msg): FakeSMTP.sent.append(msg)


@pytest.fixture()
def mail_on(app, monkeypatch):
    app.config.update(SMTP_HOST="smtp.test", SMTP_PORT=587, SMTP_USER="u@test", SMTP_PASSWORD="x",
                      SMTP_FROM="", SMTP_SECURITY="starttls")
    FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(docs, "html_to_pdf", lambda html, timeout=45: b"%PDF-1.4 fake")


def approved(app, ac):
    qid = make_quote(ac)
    ac.post(f"/quotes/{qid}/save", form_from_db(app, qid, price_0="15.500", price_1="18.000", action="approve"), page=f"/quotes/{qid}")
    assert q_row(app, qid)["approved_at"]
    return qid


def test_cannot_send_unapproved(app, ac, mail_on):
    qid = make_quote(ac)
    r = ac.post(f"/quotes/{qid}/send-email", {"to": "a@b.com"}, page=f"/quotes/{qid}")
    assert r.status_code == 302 and not FakeSMTP.sent
    assert q_row(app, qid)["status"] == "draft"


def test_email_sends_pdf_and_marks_sent(app, ac, mail_on):
    qid = approved(app, ac)
    r = ac.post(f"/quotes/{qid}/send-email", {"to": "cust@example.com", "lang": "en"}, page=f"/quotes/{qid}")
    assert r.status_code == 302 and len(FakeSMTP.sent) == 1
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "cust@example.com"
    assert any(p.get_content_type() == "application/pdf" for p in msg.iter_attachments())
    assert q_row(app, qid)["status"] == "sent"
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) n FROM audit_log WHERE action='email_sent'").fetchone()["n"] == 1


@pytest.mark.parametrize("bad", ["", "nope", "a@b", "a@b.com\nBcc: x@y.com", "a@b.com, c@d.com"])
def test_bad_addresses_rejected(app, ac, mail_on, bad):
    qid = approved(app, ac)
    ac.post(f"/quotes/{qid}/send-email", {"to": bad}, page=f"/quotes/{qid}")
    assert not FakeSMTP.sent


def test_email_off_without_smtp(app, ac):
    qid = approved(app, ac)
    ac.post(f"/quotes/{qid}/send-email", {"to": "a@b.com"}, page=f"/quotes/{qid}")
    assert q_row(app, qid)["status"] == "draft"
    assert "Email sending is off" in ac.get(f"/quotes/{qid}/share").get_data(as_text=True)


def test_whatsapp_click_marks_sent_and_needs_approval(app, ac):
    qid = make_quote(ac)
    assert ac.post(f"/quotes/{qid}/whatsapp-sent", {}, page=f"/quotes/{qid}").status_code == 400
    qid = approved(app, ac)
    assert ac.post(f"/quotes/{qid}/whatsapp-sent", {}, page=f"/quotes/{qid}").status_code == 204
    assert q_row(app, qid)["status"] == "sent"


def test_tenant_isolation_on_send(app, ac, mail_on):
    qid = approved(app, ac)
    from conftest import Client, register
    other = Client(app); register(other, "x@x.qf", "Other Co")
    r = other.post(f"/quotes/{qid}/send-email", {"to": "a@b.com"}, page="/settings")
    assert r.status_code in (403, 404) and not FakeSMTP.sent
