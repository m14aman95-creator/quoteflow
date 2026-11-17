"""Email verification for customer portal accounts."""
import re
import pytest
from conftest import Client
from quoteflow.db import get_db
from test_portal import owner, join, send_request, req_row, SLUG  # noqa: F401


@pytest.fixture()
def mail(app, monkeypatch):
    app.config.update(SMTP_HOST="smtp.test", SMTP_USER="u@test", SMTP_PASSWORD="p")
    sent = []

    def fake(cfg, to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})
        return True
    monkeypatch.setattr("quoteflow.mailer.send_notice", fake)
    return sent


def code_of(sent, to=None):
    mails = [m for m in sent if to is None or m["to"] == to]
    return re.search(r"\b(\d{6})\b", mails[-1]["subject"]).group(1)


def cust(app, phone_norm="97339991111"):
    with app.app_context():
        return dict(get_db().execute("SELECT * FROM customers WHERE phone_norm=? AND password_hash IS NOT NULL", (phone_norm,)).fetchone())


def sign_up(app, email="sara@example.com", phone="3999 1111", name="Sara Ali"):
    return join(app, phone=phone, name=name, email=email)


def verify(c, code, slug=SLUG):
    return c.post(f"/c/{slug}/verify", {"action": "verify", "code": code}, page=f"/c/{slug}/verify")


def age_cooldown(app, cid):
    with app.app_context():
        db = get_db(); db.execute("UPDATE customers SET verify_sent_at='2000-01-01 00:00:00' WHERE id=?", (cid,)); db.commit()


def test_email_is_required_and_a_code_is_sent(app, owner, mail):
    c = Client(app)
    r = c.post(f"/c/{SLUG}/register", {"name": "Sara", "phone": "39991111", "password": "customer-pass-1"}, page=f"/c/{SLUG}/register")
    assert r.status_code == 400 and "email" in r.get_data(as_text=True).lower()
    c = sign_up(app)
    assert len(mail) == 1 and mail[0]["to"] == "sara@example.com" and re.search(r"\d{6}", mail[0]["subject"])
    assert "sara@example.com" in c.get(f"/c/{SLUG}/verify").get_data(as_text=True)


def test_unverified_customer_cannot_use_the_portal(app, owner, mail):
    c = sign_up(app)
    for path in ("/home", "/new", "/account"):
        r = c.get(f"/c/{SLUG}{path}")
        assert r.status_code == 302 and r.headers["Location"].endswith("/verify"), path
    r = c.post(f"/c/{SLUG}/new", {"details": "Need AC service for two units"}, page=f"/c/{SLUG}/verify")
    assert r.status_code == 302 and r.headers["Location"].endswith("/verify")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) n FROM service_requests").fetchone()["n"] == 0


def test_correct_code_verifies_and_is_not_stored_in_clear(app, owner, mail):
    c = sign_up(app)
    code = code_of(mail)
    row = cust(app)
    assert row["verify_hash"] and code not in row["verify_hash"] and not row["email_verified_at"]
    r = verify(c, code)
    assert r.status_code == 302 and r.headers["Location"].endswith("/home")
    row = cust(app)
    assert row["email_verified_at"] and row["verify_hash"] is None
    assert c.get(f"/c/{SLUG}/home").status_code == 200
    assert send_request(c)                                                    # can now send requests
    assert c.get(f"/c/{SLUG}/verify").status_code == 302                      # nothing left to verify


def test_wrong_codes_are_limited_and_a_new_code_replaces_the_old(app, owner, mail):
    c = sign_up(app)
    good = code_of(mail)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        verify(c, bad)
    verify(c, good)                                                           # too many wrong tries: even the right code is refused
    assert not cust(app)["email_verified_at"]
    assert "Too many wrong" in c.get(f"/c/{SLUG}/verify").get_data(as_text=True)
    age_cooldown(app, cust(app)["id"])
    c.post(f"/c/{SLUG}/verify", {"action": "resend"}, page=f"/c/{SLUG}/verify")
    fresh = code_of(mail)
    assert len(mail) == 2
    if fresh != good:
        verify(c, good)
        assert not cust(app)["email_verified_at"]                             # the old code no longer works
    verify(c, fresh)
    assert cust(app)["email_verified_at"]


def test_wrong_code_message_and_format(app, owner, mail):
    c = sign_up(app)
    r = verify(c, "12ab56")
    page = c.get(f"/c/{SLUG}/verify").get_data(as_text=True)
    assert not cust(app)["email_verified_at"] and "not correct" in page


def test_expired_code_is_refused(app, owner, mail):
    c = sign_up(app)
    code = code_of(mail)
    with app.app_context():
        db = get_db(); db.execute("UPDATE customers SET verify_expires='2000-01-01 00:00:00'"); db.commit()
    verify(c, code)
    assert not cust(app)["email_verified_at"]
    assert "expired" in c.get(f"/c/{SLUG}/verify").get_data(as_text=True)


def test_resend_cooldown_and_hourly_cap(app, owner, mail):
    c = sign_up(app)
    c.post(f"/c/{SLUG}/verify", {"action": "resend"}, page=f"/c/{SLUG}/verify")
    assert len(mail) == 1                                                     # asked again within a minute: no new email
    cid = cust(app)["id"]
    for _ in range(6):
        age_cooldown(app, cid)
        c.post(f"/c/{SLUG}/verify", {"action": "resend"}, page=f"/c/{SLUG}/verify")
    assert len(mail) == 5                                                     # 5 codes an hour at most


def test_email_login_only_after_verification(app, owner, mail):
    c = sign_up(app)
    d = Client(app)
    r = d.post(f"/c/{SLUG}/login", {"identifier": "sara@example.com", "password": "customer-pass-1"}, page=f"/c/{SLUG}/login")
    assert r.status_code == 401                                               # an unconfirmed address cannot log in
    verify(c, code_of(mail))
    d = Client(app)
    r = d.post(f"/c/{SLUG}/login", {"identifier": "Sara@Example.com", "password": "customer-pass-1"}, page=f"/c/{SLUG}/login")
    assert r.status_code == 302


def test_typing_someone_elses_email_cannot_block_or_steal_it(app, owner, mail):
    attacker = sign_up(app, email="victim@example.com", phone="3999 9999", name="Attacker")
    victim = sign_up(app, email="victim@example.com", phone="3999 1111", name="Victim")      # not blocked
    assert len([m for m in mail if m["to"] == "victim@example.com"]) == 2
    verify(victim, code_of(mail))
    with app.app_context():
        rows = {r["name"]: r["email"] for r in get_db().execute("SELECT name, email FROM customers WHERE password_hash IS NOT NULL")}
    assert rows["Victim"] == "victim@example.com" and rows["Attacker"] == ""               # the unverified claim was cleared
    r = Client(app).post(f"/c/{SLUG}/register", {"name": "Late", "phone": "3999 7777", "email": "victim@example.com", "password": "customer-pass-1"}, page=f"/c/{SLUG}/register")
    assert r.status_code == 409                                                            # a verified address is taken


def test_changing_the_email_requires_confirming_it_again(app, owner, mail):
    c = sign_up(app)
    verify(c, code_of(mail))
    r = c.post(f"/c/{SLUG}/account", {"name": "Sara Ali", "email": "new@example.com"}, page=f"/c/{SLUG}/account")
    assert r.status_code == 302 and r.headers["Location"].endswith("/verify")
    assert mail[-1]["to"] == "new@example.com" and not cust(app)["email_verified_at"]
    assert c.get(f"/c/{SLUG}/home").status_code == 302
    verify(c, code_of(mail, "new@example.com"))
    assert c.get(f"/c/{SLUG}/home").status_code == 200


def test_updates_are_emailed_only_to_verified_addresses(app, owner, mail):
    c = sign_up(app)
    verify(c, code_of(mail))
    rid = send_request(c)
    mail.clear()
    owner.post(f"/requests/{rid}/status", {"status": "in_progress", "message": "On the way"}, page="/requests")
    assert [m["to"] for m in mail] == ["sara@example.com"] and "On the way" in mail[0]["body"]
    with app.app_context():
        db = get_db(); db.execute("UPDATE customers SET email_verified_at=NULL"); db.commit()
    mail.clear()
    owner.post(f"/requests/{rid}/status", {"status": "completed"}, page="/requests")
    assert not any(m["to"] == "sara@example.com" for m in mail)


def test_mail_failure_does_not_lock_the_customer_out(app, owner, monkeypatch):
    app.config.update(SMTP_HOST="smtp.test", SMTP_USER="u@test", SMTP_PASSWORD="p")
    monkeypatch.setattr("quoteflow.mailer.send_notice", lambda *a, **k: False)
    c = sign_up(app)
    page = c.get(f"/c/{SLUG}/verify").get_data(as_text=True)
    assert "Confirm your email" in page and "Send a new code" in page


def test_existing_account_without_email_can_add_one_when_verification_turns_on(app, owner, monkeypatch):
    c = join(app)                                                              # signed up while email sending was off
    app.config.update(SMTP_HOST="smtp.test", SMTP_USER="u@test", SMTP_PASSWORD="p")
    sent = []
    monkeypatch.setattr("quoteflow.mailer.send_notice", lambda cfg, to, subject, body: sent.append(to) or True)
    assert c.get(f"/c/{SLUG}/home").headers["Location"].endswith("/verify")
    r = c.post(f"/c/{SLUG}/verify", {"action": "change", "email": "late@example.com"}, page=f"/c/{SLUG}/verify")
    assert sent == ["late@example.com"]


def test_arabic_verify_page(app, owner, mail):
    c = sign_up(app)
    html = c.get(f"/c/{SLUG}/verify?lang=ar").get_data(as_text=True)
    assert 'dir="rtl"' in html and "أكّد بريدك الإلكتروني" in html


def test_owner_sees_verification_state(app, owner, mail):
    assert "Send test email" in owner.get("/portal").get_data(as_text=True)
    c = sign_up(app)
    verify(c, code_of(mail))
    rid = send_request(c)
    assert "Email verified" in owner.get(f"/requests/{rid}").get_data(as_text=True)


def test_owner_is_warned_when_email_is_not_set_up(app, owner):
    assert "Email is not set up" in owner.get("/portal").get_data(as_text=True)
