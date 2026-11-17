"""TEST-ONLY fixtures: three separate sample companies with a fixed password. Never shipped in the app."""
import os
from werkzeug.security import generate_password_hash
from quoteflow.db import get_db
from quoteflow.seed_data import AC_SERVICES, CLEANING_SERVICES, HOUSEHOLD_SERVICES, MOVING_SERVICES
from seed import _make_logo

DEMO_PASSWORD = "demo1234"

DEMO_COMPANIES = {
    "ac": {
        "email": "ac@demo.qf", "name_en": "CoolBreeze AC & Maintenance", "name_ar": "كول بريز للتكييف والصيانة",
        "cr": "123456-1", "vat_registered": 1, "vat_number": "220099887700002", "phone": "+973 3999 1234",
        "address": "Building 12, Road 3801, Block 338, Manama, Bahrain", "lang": "both", "plan": "starter",
        "color": (11, 93, 87), "initials": "CB", "services": AC_SERVICES,
        "terms_en": "50% advance for jobs above BHD 100. Parts not mentioned are charged separately after approval. Warranty: 30 days on workmanship.",
        "terms_ar": "دفعة مقدمة 50% للأعمال التي تزيد عن 100 دينار. القطع غير المذكورة تحتسب بشكل منفصل بعد الموافقة. ضمان 30 يوماً على العمل.",
    },
    "clean": {
        "email": "clean@demo.qf", "name_en": "SparkClean Services", "name_ar": "سبارك كلين للخدمات",
        "cr": "654321-1", "vat_registered": 0, "vat_number": "", "phone": "+973 3666 5555",
        "address": "Shop 4, Building 88, Road 1205, Block 312, Riffa, Bahrain", "lang": "en", "plan": "free",
        "color": (180, 83, 9), "initials": "SC", "services": CLEANING_SERVICES,
        "terms_en": "Payment on completion of service. Cleaning supplies and equipment included unless stated. Rescheduling requires 24 hours notice.",
        "terms_ar": "الدفع عند إتمام الخدمة. مواد ومعدات التنظيف مشمولة ما لم يذكر خلاف ذلك. إعادة الجدولة تتطلب إشعاراً قبل 24 ساعة.",
    },
    "home": {
        "email": "home@demo.qf", "name_en": "HomeEase Household & Moving", "name_ar": "هوم إيز للخدمات المنزلية والنقل",
        "cr": "778899-1", "vat_registered": 1, "vat_number": "220077665500003", "phone": "+973 3777 8899",
        "address": "Workshop 7, Building 21, Road 4210, Block 942, Hamad Town, Bahrain", "lang": "both", "plan": "professional",
        "color": (30, 64, 175), "initials": "HE", "services": HOUSEHOLD_SERVICES + MOVING_SERVICES,
        "terms_en": "Quotation covers the work described only. Access, parking and lift booking are the customer's responsibility. 50% deposit to confirm a move. Cancellation less than 24 hours before the job may incur a call-out charge.",
        "terms_ar": "يشمل العرض الأعمال الموصوفة فقط. تأمين الدخول والمواقف وحجز المصعد مسؤولية العميل. دفعة مقدمة 50% لتأكيد النقل. الإلغاء قبل أقل من 24 ساعة قد يترتب عليه رسوم زيارة.",
    },
}


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
        from seed_quotes import seed_quotes, AC, CLEAN, HOME
        seed_quotes(app, pairs=(("ac@demo.qf", AC), ("clean@demo.qf", CLEAN), ("home@demo.qf", HOME)))
        return created


