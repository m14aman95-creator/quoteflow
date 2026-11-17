import os
import re
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from quoteflow import create_app  # noqa: E402


@pytest.fixture()
def app():
    tmp = tempfile.mkdtemp()
    app = create_app({"DATABASE": os.path.join(tmp, "t.sqlite"), "UPLOAD_DIR": os.path.join(tmp, "up"),
                      "TESTING": True, "AI_PROVIDER": "offline", "ANTHROPIC_API_KEY": ""})
    return app


class Client:
    """Test client that handles CSRF tokens automatically."""
    def __init__(self, app):
        self.c = app.test_client()

    def token(self, path="/login"):
        html = self.c.get(path).get_data(as_text=True)
        m = re.search(r'name="_csrf" value="([0-9a-f]+)"', html)
        assert m, "no csrf token on " + path
        return m.group(1)

    def post(self, path, data=None, page=None, **kw):
        data = dict(data or {})
        data["_csrf"] = self.token(page or path if page else "/login")
        return self.c.post(path, data=data, **kw)

    def get(self, path, **kw):
        return self.c.get(path, **kw)


def register(client, email="owner@a.qf", company="Alpha Co", pw="password123"):
    return client.post("/register", {"company_name": company, "email": email, "password": pw, "name": "Owner",
                                     "username": email.split("@")[0] + "_user"},
                       page="/register")


@pytest.fixture()
def client(app):
    return Client(app)


@pytest.fixture()
def two_clients(app):
    a, b = Client(app), Client(app)
    register(a, "a@a.qf", "Alpha Co")
    register(b, "b@b.qf", "Beta Co")
    return a, b
