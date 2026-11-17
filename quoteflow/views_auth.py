import re
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from .db import get_db
from . import audit
from .security import current_user

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        company = request.form.get("company_name", "").strip()
        name = request.form.get("name", "").strip()
        if not username and "@" in email:                       # older forms only sent an email
            username = re.sub(r"[^A-Za-z0-9._-]", "", email.split("@")[0])[:30]
        db = get_db()
        error = None
        if not company:
            error = "Please enter your company name."
        elif not USERNAME_RE.match(username):
            error = "Username must be 3-30 characters: letters, numbers, dot, dash or underscore."
        elif email and ("@" not in email or len(email) > 200):
            error = "Please enter a valid email address or leave it empty."
        elif len(pw) < 8:
            error = "Password must be at least 8 characters."
        elif db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            error = "That username is taken. Please choose another."
        elif email and db.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
            error = "An account with this email already exists."
        if error:
            flash(error, "error")
            return render_template("register.html", form=request.form), 400
        email_db = email or f"{username.lower()}@local.invalid"
        cur = db.execute("INSERT INTO companies (name_en, email) VALUES (?,?)", (company, email))
        cid = cur.lastrowid
        cur = db.execute(
            "INSERT INTO users (company_id, email, username, name, password_hash, role) VALUES (?,?,?,?,?, 'owner')",
            (cid, email_db, username, name, generate_password_hash(pw)),
        )
        audit.log(cid, cur.lastrowid, "company", cid, "register")
        db.commit()
        session.clear()
        session["uid"] = cur.lastrowid
        return redirect(url_for("main.onboarding"))
    return render_template("register.html", form={})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        ident = (request.form.get("username") or request.form.get("email") or "").strip().lower()
        row = get_db().execute("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?", (ident, ident)).fetchone() if ident else None
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            session.clear()
            session["uid"] = row["id"]
            audit.log(row["company_id"], row["id"], "user", row["id"], "login")
            get_db().commit()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
        flash("Incorrect username or password.", "error")
        return render_template("login.html"), 401
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
