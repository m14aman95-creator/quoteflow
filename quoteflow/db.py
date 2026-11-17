"""SQLite storage. Every business table carries company_id (tenant isolation).
All money is stored as integer fils (1 BHD = 1000 fils). Never floats."""
import sqlite3
import os
from flask import g, current_app

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name_en TEXT NOT NULL,
    name_ar TEXT NOT NULL DEFAULT '',
    logo_path TEXT,
    cr_number TEXT NOT NULL DEFAULT '',
    vat_registered INTEGER NOT NULL DEFAULT 0,
    vat_number TEXT NOT NULL DEFAULT '',
    vat_rate_bp INTEGER NOT NULL DEFAULT 1000,       -- basis points: 1000 = 10.00%
    vat_confirmed_at TEXT,                            -- user must confirm VAT settings
    currency TEXT NOT NULL DEFAULT 'BHD',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    default_terms_en TEXT NOT NULL DEFAULT '',
    default_terms_ar TEXT NOT NULL DEFAULT '',
    validity_days INTEGER NOT NULL DEFAULT 14,
    preferred_lang TEXT NOT NULL DEFAULT 'en',        -- en | ar | both
    retention_days INTEGER NOT NULL DEFAULT 30,       -- raw enquiry text kept this long
    plan TEXT NOT NULL DEFAULT 'free',
    quote_seq INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',               -- owner | admin | staff (role-ready)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name_en TEXT NOT NULL,
    name_ar TEXT NOT NULL DEFAULT '',
    desc_en TEXT NOT NULL DEFAULT '',
    desc_ar TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'each',
    default_price_fils INTEGER,                       -- optional, user-entered only
    tax_class TEXT NOT NULL DEFAULT 'standard',       -- standard | zero | exempt
    keywords TEXT NOT NULL DEFAULT '',                -- comma separated, EN/AR, for matching
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    customer_id INTEGER REFERENCES customers(id),
    raw_text TEXT,                                    -- NULL once purged by retention
    purge_after TEXT,
    extraction_json TEXT,                             -- validated structured result
    provider TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    enquiry_id INTEGER REFERENCES enquiries(id),
    customer_id INTEGER REFERENCES customers(id),
    number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',             -- draft|sent|follow_up|accepted|rejected|expired
    language TEXT NOT NULL DEFAULT 'en',              -- en | ar | both
    valid_until TEXT,
    discount_type TEXT NOT NULL DEFAULT 'none',       -- none | percent | fixed
    discount_value INTEGER NOT NULL DEFAULT 0,        -- basis points if percent, fils if fixed
    terms_en TEXT NOT NULL DEFAULT '',
    terms_ar TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    subtotal_fils INTEGER NOT NULL DEFAULT 0,
    discount_fils INTEGER NOT NULL DEFAULT 0,
    vat_fils INTEGER NOT NULL DEFAULT 0,
    total_fils INTEGER NOT NULL DEFAULT 0,
    approved_by INTEGER REFERENCES users(id),
    approved_at TEXT,
    feedback TEXT,                                    -- as_is|minor|major|unusable
    feedback_at TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quote_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    quote_id INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    service_id INTEGER REFERENCES services(id),
    title_en TEXT NOT NULL DEFAULT '',
    title_ar TEXT NOT NULL DEFAULT '',
    desc_en TEXT NOT NULL DEFAULT '',
    desc_ar TEXT NOT NULL DEFAULT '',
    customer_words TEXT NOT NULL DEFAULT '',          -- what the customer actually wrote (trust cue)
    quantity_milli INTEGER NOT NULL DEFAULT 1000,     -- quantity x 1000 (integer)
    unit TEXT NOT NULL DEFAULT 'each',
    unit_price_fils INTEGER,                          -- NULL = not priced yet
    price_source TEXT NOT NULL DEFAULT 'none',        -- none | catalogue | manual
    tax_class TEXT NOT NULL DEFAULT 'standard',
    origin TEXT NOT NULL DEFAULT 'manual',            -- customer | ai | manual (trust cue)
    uncertain INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    user_id INTEGER,
    entity TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage (
    company_id INTEGER NOT NULL,
    month TEXT NOT NULL,                              -- YYYY-MM
    quotes_created INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (company_id, month)
);
CREATE TABLE IF NOT EXISTS service_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    ref TEXT NOT NULL,                                -- R-2026-0001, shown to the customer and the owner
    service_id INTEGER REFERENCES services(id),
    service_label TEXT NOT NULL DEFAULT '',           -- service name as the customer saw it
    details TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    preferred_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',               -- new|reviewing|quoted|accepted|scheduled|in_progress|completed|declined|cancelled
    enquiry_id INTEGER REFERENCES enquiries(id),
    quote_id INTEGER REFERENCES quotes(id),
    scheduled_for TEXT NOT NULL DEFAULT '',
    owner_seen INTEGER NOT NULL DEFAULT 0,            -- 0 = has something new for the owner
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS request_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    request_id INTEGER NOT NULL REFERENCES service_requests(id) ON DELETE CASCADE,
    actor TEXT NOT NULL DEFAULT 'system',             -- customer | owner | system
    kind TEXT NOT NULL DEFAULT 'status',              -- status | message
    status TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_quotes_company ON quotes(company_id, created_at);
CREATE INDEX IF NOT EXISTS idx_items_quote ON quote_items(quote_id);
CREATE INDEX IF NOT EXISTS idx_services_company ON services(company_id);
CREATE INDEX IF NOT EXISTS idx_customers_company ON customers(company_id);
CREATE INDEX IF NOT EXISTS idx_audit_company ON audit_log(company_id, id);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columns added after the first release. Added in place so existing databases keep working.
MIGRATIONS = {
    "quotes": [("share_token", "TEXT"), ("viewed_at", "TEXT"), ("view_count", "INTEGER NOT NULL DEFAULT 0"),
               ("responded_at", "TEXT"), ("response_name", "TEXT NOT NULL DEFAULT ''"),
               ("response_note", "TEXT NOT NULL DEFAULT ''"), ("selected_optional", "TEXT NOT NULL DEFAULT ''")],
    "quote_items": [("optional", "INTEGER NOT NULL DEFAULT 0")],
    "users": [("username", "TEXT")],
    "companies": [("slug", "TEXT"), ("portal_enabled", "INTEGER NOT NULL DEFAULT 1"),
                  ("request_seq", "INTEGER NOT NULL DEFAULT 0"),
                  ("portal_verify", "INTEGER NOT NULL DEFAULT 1")],
    "customers": [("password_hash", "TEXT"), ("phone_norm", "TEXT NOT NULL DEFAULT ''"), ("last_login_at", "TEXT"),
                  ("email_verified_at", "TEXT"), ("verify_hash", "TEXT"), ("verify_expires", "TEXT"),
                  ("verify_tries", "INTEGER NOT NULL DEFAULT 0"), ("verify_sent_at", "TEXT")],
}


def _migrate(con):
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(lower(username)) WHERE username IS NOT NULL")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_token ON quotes(share_token) WHERE share_token IS NOT NULL")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_slug ON companies(lower(slug)) WHERE slug IS NOT NULL")
    # a customer login is unique per business by phone and by email (CRM-only customers without a login are not affected)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cust_login_phone ON customers(company_id, phone_norm) "
                "WHERE password_hash IS NOT NULL AND phone_norm <> ''")
    con.execute("DROP INDEX IF EXISTS idx_cust_login_email")      # replaced: only a VERIFIED email is unique (an unverified one cannot block its real owner)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cust_verified_email ON customers(company_id, lower(email)) "
                "WHERE password_hash IS NOT NULL AND email <> '' AND email_verified_at IS NOT NULL")
    con.execute("CREATE INDEX IF NOT EXISTS idx_requests_company ON service_requests(company_id, status, id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_requests_customer ON service_requests(customer_id, id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_request ON request_events(request_id, id)")
    con.row_factory = sqlite3.Row
    from .slugs import ensure_slug, norm_phone
    for r in con.execute("SELECT id, phone FROM customers WHERE phone_norm='' AND phone<>''").fetchall():
        con.execute("UPDATE customers SET phone_norm=? WHERE id=?", (norm_phone(r["phone"]), r["id"]))
    for r in con.execute("SELECT id FROM companies WHERE slug IS NULL").fetchall():
        ensure_slug(con, r["id"])


def init_db(app):
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    con = sqlite3.connect(app.config["DATABASE"])
    con.executescript(SCHEMA)
    _migrate(con)
    con.commit()
    con.close()
    app.teardown_appcontext(close_db)
