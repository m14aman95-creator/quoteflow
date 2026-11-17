"""Run the development server:  python run.py   (set PORT to change the port)"""
import os
from quoteflow import create_app

app = create_app()

# Demo hosting (e.g. Render free tier, where the disk resets on every sleep):
# set QF_SEED_DEMO=1 (and ADMIN_USERNAME / ADMIN_PASSWORD) and the demo account is recreated on start-up. Safe to repeat.
if os.environ.get("QF_SEED_DEMO") == "1":
    from seed import seed_all, credentials_from_env
    _user, _pw, _generated = credentials_from_env()
    if seed_all(app, _user, _pw) and _generated:
        print(f"[QuoteFlow] Demo account created. Username: {_user}  Password: {_pw}  (set ADMIN_PASSWORD to choose your own)", flush=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
