"""Create the first business owner account:

    python seed.py --username yourname --password 'YourStrongPassword' [--sample]

The account is a normal business account that offers every starter service (AC, cleaning, household, furniture moving).
There is no built-in or default login. --sample also adds a few past quotations so the dashboard is not empty."""
import os
from PIL import Image, ImageDraw, ImageFont
from werkzeug.security import generate_password_hash

from quoteflow import create_app
from quoteflow.db import get_db
from quoteflow.slugs import ensure_slug


def _make_logo(path, color, initials):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGBA", (120, 120), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 119, 119), radius=24, fill=color + (255,))
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
    except OSError:
        font = ImageFont.load_default()
    w = d.textlength(initials, font=font)
    d.text(((120 - w) / 2, 28), initials, font=font, fill=(255, 255, 255, 255))
    img.save(path, "PNG")


def bootstrap_owner(app, username, password, email=None, sample=False):
    """One business with every starter service and one owner login. Safe to repeat: does nothing if the username exists."""
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
        ensure_slug(db, cid)
        db.commit()
    if sample:
        from seed_quotes import seed_quotes, ALL
        seed_quotes(app, pairs=((username, ALL),))
    return True


def seed_all(app, username, password, email=None):
    """Owner account plus sample quotation history (used by the tests and the evaluation)."""
    return bootstrap_owner(app, username, password, email, sample=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Create the first business owner account (all starter services).")
    ap.add_argument("--username", required=True, help="login username")
    ap.add_argument("--password", required=True, help="password (at least 8 characters)")
    ap.add_argument("--sample", action="store_true", help="also add sample past quotations")
    a = ap.parse_args()
    if len(a.password) < 8:
        raise SystemExit("The password must be at least 8 characters.")
    made = bootstrap_owner(create_app(), a.username, a.password, sample=a.sample)
    print(f"Created the account '{a.username}' with all starter services." if made
          else f"Account '{a.username}' already exists. Nothing changed.")
