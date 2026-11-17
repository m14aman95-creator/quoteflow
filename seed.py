"""Create demo data:  python seed.py [--reset]
Two demo businesses (AC maintenance, cleaning). Password for both: demo1234"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont
from werkzeug.security import generate_password_hash

from quoteflow import create_app
from quoteflow.db import get_db
from quoteflow.seed_data import DEMO_COMPANIES
from quoteflow.timeutil import utcnow

DEMO_PASSWORD = "demo1234"   # only for the legacy test companies


def _make_logo(path, color, initials):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGBA", (360, 120), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 119, 119), radius=24, fill=color + (255,))
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
    except OSError:
        font = ImageFont.load_default()
    w = d.textlength(initials, font=font)
    d.text(((120 - w) / 2, 28), initials, font=font, fill=(255, 255, 255, 255))
    img.save(path, "PNG")


def seed_legacy(app, reset=False):
    with app.app_context():
        db = get_db()
        if reset:
            for spec in DEMO_COMPANIES.values():
                row = db.execute("SELECT company_id FROM users WHERE email=?", (spec["email"],)).fetchone()
                if row:
                    cid = row["company_id"]
                    for t in ("quote_items", "quotes", "enquiries", "customers", "services", "audit_log", "usage", "users"):
                        db.execute(f"DELETE FROM {t} WHERE company_id=?", (cid,))
                    db.execute("DELETE FROM companies WHERE id=?", (cid,))
            db.commit()
        created = []
        for key, s in DEMO_COMPANIES.items():
            if db.execute("SELECT 1 FROM users WHERE email=?", (s["email"],)).fetchone():
                continue
            cur = db.execute(
                """INSERT INTO companies (name_en, name_ar, cr_number, vat_registered, vat_number, vat_rate_bp,
                   vat_confirmed_at, phone, email, address, default_terms_en, default_terms_ar, validity_days,
                   preferred_lang, plan) VALUES (?,?,?,?,?,1000,datetime('now'),?,?,?,?,?,14,?,?)""",
                (s["name_en"], s["name_ar"], s["cr"], s["vat_registered"], s["vat_number"], s["phone"], s["email"],
                 s["address"], s["terms_en"], s["terms_ar"], s["lang"], s["plan"]))
            cid = cur.lastrowid
            db.execute("INSERT INTO users (company_id, email, name, password_hash, role) VALUES (?,?,?,?, 'owner')",
                       (cid, s["email"], "Demo Owner", generate_password_hash(DEMO_PASSWORD)))
            logo = os.path.join(app.config["UPLOAD_DIR"], str(cid), "logo.png")
            _make_logo(logo, s["color"], s["initials"])
            db.execute("UPDATE companies SET logo_path=? WHERE id=?", (logo, cid))
            for (en, ar, den, dar, unit, price, tax, kw) in s["services"]:
                db.execute("""INSERT INTO services (company_id, name_en, name_ar, desc_en, desc_ar, unit,
                              default_price_fils, tax_class, keywords) VALUES (?,?,?,?,?,?,?,?,?)""",
                           (cid, en, ar, den, dar, unit, price, tax, kw))
            created.append(s["email"])
        db.commit()
        from seed_quotes import seed_quotes
        seed_quotes(app)
        return created


def seed_all(app, username, password, email=None):
    """The single demo account: every service in one company. Safe to repeat (does nothing if it exists)."""
    from quoteflow.seed_data import ALL_COMPANY as S
    with app.app_context():
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            return False
        email = (email or f"{username.lower()}@local.invalid").lower()
        cur = db.execute(
            """INSERT INTO companies (name_en, name_ar, cr_number, vat_registered, vat_number, vat_rate_bp,
               vat_confirmed_at, phone, email, address, default_terms_en, default_terms_ar, validity_days,
               preferred_lang, plan) VALUES (?,?,?,?,?,1000,datetime('now'),?,?,?,?,?,14,?,?)""",
            (S["name_en"], S["name_ar"], S["cr"], S["vat_registered"], S["vat_number"], S["phone"], email,
             S["address"], S["terms_en"], S["terms_ar"], S["lang"], S["plan"]))
        cid = cur.lastrowid
        db.execute("INSERT INTO users (company_id, email, username, name, password_hash, role) VALUES (?,?,?,?,?, 'owner')",
                   (cid, email, username, "Owner", generate_password_hash(password)))
        logo = os.path.join(app.config["UPLOAD_DIR"], str(cid), "logo.png")
        _make_logo(logo, S["color"], S["initials"])
        db.execute("UPDATE companies SET logo_path=? WHERE id=?", (logo, cid))
        for (en, ar, den, dar, unit, price, tax, kw) in S["services"]:
            db.execute("""INSERT INTO services (company_id, name_en, name_ar, desc_en, desc_ar, unit,
                          default_price_fils, tax_class, keywords) VALUES (?,?,?,?,?,?,?,?,?)""",
                       (cid, en, ar, den, dar, unit, price, tax, kw))
        db.commit()
    from seed_quotes import seed_quotes, ALL
    seed_quotes(app, pairs=((username, ALL),))
    return True


def credentials_from_env():
    """ADMIN_USERNAME / ADMIN_PASSWORD from the environment; a missing password is generated and printed once."""
    import secrets
    user = (os.environ.get("ADMIN_USERNAME") or "admin").strip()
    pw = os.environ.get("ADMIN_PASSWORD") or ""
    generated = False
    if not pw:
        pw, generated = secrets.token_urlsafe(9), True
    return user, pw, generated


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Create the demo account (all services in one company).")
    ap.add_argument("--username", help="login username (or env ADMIN_USERNAME, default 'admin')")
    ap.add_argument("--password", help="password (or env ADMIN_PASSWORD; generated if missing)")
    ap.add_argument("--legacy", action="store_true", help="three separate demo companies (used by the tests)")
    ap.add_argument("--reset", action="store_true", help="with --legacy: rebuild the three companies")
    a = ap.parse_args()
    app = create_app()
    if a.legacy:
        print("Created:", seed_legacy(app, reset=a.reset) or "nothing (already exist)")
        print("Log in with ac@demo.qf, clean@demo.qf or home@demo.qf / password:", DEMO_PASSWORD)
    else:
        if a.username:
            os.environ["ADMIN_USERNAME"] = a.username
        if a.password:
            os.environ["ADMIN_PASSWORD"] = a.password
        user, pw, generated = credentials_from_env()
        made = seed_all(app, user, pw)
        if not made:
            print(f"Account '{user}' already exists. Nothing changed.")
        else:
            print(f"Created the account with all services.\n  Username: {user}\n  Password: {pw}" + ("   (generated: save it now)" if generated else ""))
