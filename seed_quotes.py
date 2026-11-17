"""Sample quotation history for the demo accounts (past months, so they do not use this month's plan quota)."""
from datetime import date, timedelta
from quoteflow.db import get_db
from quoteflow.money import compute_quote, LineInput

# (customer, phone, location, status, days_ago, [(service name_en prefix, qty), ...], discount_pct)
AC = [
    ("Fatima Al Khalifa", "+973 3912 4455", "Seef, Block 428", "accepted", 52, [("AC general service", 4)], 0),
    ("Hamad Contracting", "+973 3344 8899", "Riffa, Block 928", "accepted", 40, [("AC installation", 2), ("AC general service", 2)], 5),
    ("Yusuf Ebrahim", "+973 3677 2211", "Juffair", "rejected", 33, [("AC gas refill", 3)], 0),
    ("Maryam Saleh", "+973 3700 1234", "Saar", "follow_up", 9, [("AC water leak", 1), ("AC inspection", 1)], 0),
    ("Dr. Ali Hassan Clinic", "+973 3555 6677", "Manama, Road 1706", "sent", 4, [("Annual AC maintenance", 6)], 10),
    ("Reem Trading", "+973 3222 8800", "Hidd", "sent", 31, [("AC general service", 3)], 0),
]
HOME = [
    ("Abdulla Al Sayed", "+973 3801 2020", "Amwaj Islands", "accepted", 48, [("Local home move: 2-bedroom", 1), ("Packing service", 3), ("Dismantle and reassemble", 4)], 0),
    ("Nasser Yaqoob", "+973 3611 4545", "Saar", "accepted", 37, [("Plumbing call-out", 1), ("Tap, mixer", 2)], 0),
    ("Elena Petrova", "+973 3355 7799", "Juffair", "rejected", 28, [("Local home move: studio", 1), ("No-lift", 3)], 5),
    ("Jassim Contracting", "+973 3222 9911", "Hamad Town", "follow_up", 8, [("Interior painting", 4), ("Handyman", 6)], 0),
    ("Maha Al Zayani", "+973 3700 6600", "Riffa Views", "sent", 3, [("Local home move: 3-bedroom", 1), ("Packing boxes", 40), ("Storage", 2)], 10),
    ("Tariq Hassan", "+973 3499 1212", "Manama", "sent", 26, [("TV wall mounting", 2), ("Furniture assembly", 3)], 0),
]
CLEAN = [
    ("Noora Abdulla", "+973 3811 9090", "Janabiyah", "accepted", 55, [("Villa deep cleaning", 1)], 0),
    ("Bahrain Dental Care", "+973 3922 3344", "Seef", "accepted", 42, [("Office cleaning", 2)], 0),
    ("Khalid Mansoor", "+973 3600 7788", "Hamad Town", "rejected", 30, [("Apartment deep cleaning", 1), ("Sofa cleaning", 5)], 0),
    ("Sara Johnson", "+973 3466 1100", "Juffair", "follow_up", 9, [("Move-in", 1), ("Window cleaning", 12)], 0),
    ("Layla Mohamed", "+973 3288 5566", "Riffa", "sent", 3, [("Regular home cleaning", 4)], 0),
    ("Omar Villa", "+973 3111 4400", "Budaiya", "sent", 29, [("Villa deep cleaning", 1)], 0),
]


def seed_quotes(app, pairs=None):
    with app.app_context():
        db = get_db()
        for login, data in (pairs or (("ac@demo.qf", AC), ("clean@demo.qf", CLEAN), ("home@demo.qf", HOME))):
            u = db.execute("SELECT * FROM users WHERE lower(email)=lower(?) OR lower(username)=lower(?)", (login, login)).fetchone()
            if not u:
                continue
            c = dict(db.execute("SELECT * FROM companies WHERE id=?", (u["company_id"],)).fetchone())
            if db.execute("SELECT 1 FROM quotes WHERE company_id=?", (c["id"],)).fetchone():
                continue
            services = {s["name_en"]: dict(s) for s in db.execute("SELECT * FROM services WHERE company_id=?", (c["id"],))}
            for name, phone, loc, status, ago, lines, disc in data:
                cust = db.execute("INSERT INTO customers (company_id, name, phone, location) VALUES (?,?,?,?)",
                                  (c["id"], name, phone, loc)).lastrowid
                created = date.today() - timedelta(days=ago)
                valid = created + timedelta(days=c["validity_days"])
                db.execute("UPDATE companies SET quote_seq = quote_seq + 1 WHERE id=?", (c["id"],))
                seq = db.execute("SELECT quote_seq FROM companies WHERE id=?", (c["id"],)).fetchone()["quote_seq"]
                items = []
                for prefix, qty in lines:
                    svc = next(s for n, s in services.items() if n.startswith(prefix))
                    items.append((svc, qty * 1000))
                tot = compute_quote([LineInput(q, s["default_price_fils"], s["tax_class"]) for s, q in items],
                                    "percent" if disc else "none", disc * 100, bool(c["vat_registered"]), c["vat_rate_bp"])
                qid = db.execute(
                    """INSERT INTO quotes (company_id, customer_id, number, status, language, valid_until, terms_en, terms_ar,
                       discount_type, discount_value, subtotal_fils, discount_fils, vat_fils, total_fils, approved_at,
                       approved_by, sent_at, feedback, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (c["id"], cust, f"Q-{created.year}-{seq:04d}", status, c["preferred_lang"], valid.isoformat(),
                     c["default_terms_en"], c["default_terms_ar"], "percent" if disc else "none", disc * 100,
                     tot.subtotal_fils, tot.discount_fils, tot.vat_fils, tot.total_fils, f"{created} 10:00:00", u["id"],
                     f"{created} 11:00:00", "as_is" if status == "accepted" else "minor", f"{created} 09:00:00",
                     f"{created} 11:00:00")).lastrowid
                for pos, (svc, q) in enumerate(items):
                    db.execute(
                        """INSERT INTO quote_items (company_id, quote_id, position, service_id, title_en, title_ar, desc_en,
                           desc_ar, quantity_milli, unit, unit_price_fils, price_source, tax_class, origin, approved)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'catalogue', ?, 'customer', 1)""",
                        (c["id"], qid, pos, svc["id"], svc["name_en"], svc["name_ar"], svc["desc_en"], svc["desc_ar"], q,
                         svc["unit"], svc["default_price_fils"], svc["tax_class"]))
        db.commit()


ALL = AC + CLEAN + HOME
