"""Run the development server:  python run.py   (set PORT to change the port)"""
import os
from quoteflow import create_app

app = create_app()

# First-owner bootstrap (useful on hosts such as the Render free tier, where the disk resets when the service sleeps).
# If BOTH ADMIN_USERNAME and ADMIN_PASSWORD are set, that owner account is created on start-up when it does not exist.
# Nothing is created otherwise: there is no default login, and anyone can register their own business at /register.
_user = (os.environ.get("ADMIN_USERNAME") or "").strip()
_pw = os.environ.get("ADMIN_PASSWORD") or ""
if _user and _pw:
    from seed import bootstrap_owner
    bootstrap_owner(app, _user, _pw, sample=os.environ.get("QF_SAMPLE_DATA") == "1")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
