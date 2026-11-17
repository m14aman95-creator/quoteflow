import time
from flask import Flask, session, g, request, url_for, current_app
from .config import Config
from .db import init_db
from .security import csrf_token, check_csrf, current_company, current_user
from .i18n import make_t
from .usage import usage_summary


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # correct https links behind Render's proxy
    if test_config:
        app.config.update(test_config)
    init_db(app)

    from .views_auth import bp as auth_bp
    from .views_main import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.route("/sw.js")
    def service_worker():
        resp = app.send_static_file("sw.js")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # Optional feature blueprints (added stage by stage)
    for modname in ("views_catalogue", "views_quotes", "views_public"):
        try:
            mod = __import__(f"quoteflow.{modname}", fromlist=["bp"])
            app.register_blueprint(mod.bp)
        except ModuleNotFoundError as exc:
            if exc.name != f"quoteflow.{modname}":
                raise

    app.before_request(check_csrf)

    @app.before_request
    def _purge_sometimes():
        # cheap retention enforcement: at most once per 10 minutes per process
        now = time.time()
        if now - app.config.get("_last_purge", 0) > 600:
            app.config["_last_purge"] = now
            from .retention import purge_expired
            purge_expired()

    def ep_url(name, **kw):
        return url_for(name, **kw) if name in current_app.view_functions else url_for("main.dashboard")

    @app.context_processor
    def inject():
        u = current_user()
        c = current_company()
        ui = session.get("ui_lang") or ("ar" if c and c.get("preferred_lang") == "ar" else "en")
        return {"ep_url": ep_url, "csrf_token": csrf_token, "me": u, "company": c, "ui_lang": ui,
                "t": make_t(ui), "dir": "rtl" if ui == "ar" else "ltr",
                "nav_usage": usage_summary(c) if c else None}

    @app.template_filter("bhd")
    def bhd(fils):
        if fils is None:
            return "—"
        sign = "-" if fils < 0 else ""
        fils = abs(int(fils))
        return f"{sign}{fils // 1000}.{fils % 1000:03d}"

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    return app
