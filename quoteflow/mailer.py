"""Outgoing email. Two ways to send, chosen by what is configured:

1. An HTTPS email API (Brevo). Use this on hosts that block SMTP ports, such as Render's free plan.
   Needs BREVO_API_KEY and a sender address that is verified in Brevo (SMTP_FROM or MAIL_FROM).
2. Plain SMTP (SMTP_HOST, SMTP_USER, SMTP_PASSWORD), for example Gmail with an App Password.

Quotations are only emailed after a human approves and clicks Send. Notices and verification codes are short plain-text mails.
Nothing in here may crash a web request: send_notice never raises, and send_quote_email raises only MailError with a readable message."""
import base64
import json
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class MailError(Exception):
    pass


def valid_email(addr: str) -> bool:
    return bool(addr) and len(addr) <= 254 and bool(EMAIL_RE.match(addr)) and "\n" not in addr and "\r" not in addr


def _sender(cfg) -> str:
    return (cfg.get("MAIL_FROM") or cfg.get("SMTP_FROM") or cfg.get("SMTP_USER") or "").strip()


def api_enabled(cfg) -> bool:
    return bool(cfg.get("BREVO_API_KEY") and valid_email(_sender(cfg)))


def smtp_enabled(cfg) -> bool:
    return bool(cfg.get("SMTP_HOST") and cfg.get("SMTP_USER") and cfg.get("SMTP_PASSWORD"))


def mail_enabled(cfg) -> bool:
    return api_enabled(cfg) or smtp_enabled(cfg)


def method(cfg) -> str:
    return "api" if api_enabled(cfg) else ("smtp" if smtp_enabled(cfg) else "")


# ------------------------------------------------------------------ the two transports
def _send_api(cfg, *, to, subject, body, from_name, reply_to, pdf_bytes, pdf_name):
    payload = {"sender": {"email": _sender(cfg), **({"name": from_name[:80]} if from_name else {})},
               "to": [{"email": to}], "subject": subject, "textContent": body}
    if reply_to and valid_email(reply_to):
        payload["replyTo"] = {"email": reply_to}
    if pdf_bytes:
        payload["attachment"] = [{"name": pdf_name or "quotation.pdf", "content": base64.b64encode(pdf_bytes).decode()}]
    req = urllib.request.Request(cfg.get("BREVO_API_URL") or BREVO_URL, data=json.dumps(payload).encode(), method="POST",
                                 headers={"api-key": cfg["BREVO_API_KEY"], "content-type": "application/json", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status >= 300:
            raise MailError(f"The email service answered {resp.status}.")


def _send_smtp(cfg, *, to, subject, body, from_name, reply_to, pdf_bytes, pdf_name):
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, _sender(cfg))) if from_name else _sender(cfg)
    msg["To"] = to
    if reply_to and valid_email(reply_to):
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)
    if pdf_bytes:
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=pdf_name or "quotation.pdf")
    mode = cfg.get("SMTP_SECURITY", "starttls")
    if mode == "ssl":
        smtp = smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20)
    with smtp:
        if mode == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        smtp.send_message(msg)


def explain(exc, cfg) -> str:
    """A readable reason for a failed send. Never includes passwords or keys."""
    host = cfg.get("SMTP_HOST") or "the email service"
    if isinstance(exc, MailError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            detail = (json.loads(exc.read().decode("utf-8", "replace")).get("message") or "")[:140]
        except Exception:
            pass
        if exc.code in (401, 403):
            return "Brevo refused the API key or the sender address. Check BREVO_API_KEY, and that the sender is verified in Brevo." + (f" ({detail})" if detail else "")
        return f"Brevo rejected the email (code {exc.code})." + (f" {detail}" if detail else "")
    if isinstance(exc, UnicodeError):
        return "The SMTP username or password contains a hidden special character (often a non-breaking space copied from a web page). Retype it."
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "The mail server refused the username or password. For Gmail use a 16-letter App Password (letters only, no spaces)."
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, urllib.error.URLError)):
        return (f"Could not reach {host}. Some hosts, including Render's free plan, block outgoing email ports. "
                "Use the Brevo email API (BREVO_API_KEY) instead of SMTP.")
    if isinstance(exc, smtplib.SMTPException):
        return f"The mail server refused the message ({type(exc).__name__})."
    return f"The email could not be sent ({type(exc).__name__})."


def deliver(cfg, *, to, subject, body, from_name="", reply_to="", pdf_bytes=None, pdf_name=""):
    """Send one message. Raises MailError(readable reason) on any failure."""
    if not mail_enabled(cfg):
        raise MailError("Email is not set up on this server (set BREVO_API_KEY, or the SMTP settings).")
    if not valid_email(to):
        raise MailError("The email address is not valid.")
    args = dict(to=to, subject=(subject or "").replace("\n", " ").replace("\r", " ")[:200], body=body,
                from_name=(from_name or "").replace("\n", " ").replace("\r", " ")[:80], reply_to=reply_to,
                pdf_bytes=pdf_bytes, pdf_name=pdf_name)
    try:
        (_send_api if api_enabled(cfg) else _send_smtp)(cfg, **args)
    except MailError:
        raise
    except Exception as e:                      # any transport problem becomes a readable MailError, never a crash
        raise MailError(explain(e, cfg)) from None


# ------------------------------------------------------------------ what the rest of the app calls
def send_quote_email(cfg, *, to, company_name, reply_to, subject, body, pdf_bytes, pdf_name):
    deliver(cfg, to=to, subject=subject, body=body, from_name=company_name, reply_to=reply_to, pdf_bytes=pdf_bytes, pdf_name=pdf_name)


def send_notice(cfg, *, to, subject, body):
    """Short plain-text notice or code. Never raises: returns True if it was sent."""
    try:
        deliver(cfg, to=to, subject=subject, body=body)
        return True
    except Exception:
        return False


def send_test(cfg, to):
    """For the owner's 'send me a test email' button. Returns (ok, readable message)."""
    try:
        deliver(cfg, to=to, subject="QuoteFlow AI test email",
                body="This is a test email from QuoteFlow AI. If you can read it, customer verification codes and quotation emails will work.")
        return True, f"Test email sent to {to} using {'the Brevo email API' if api_enabled(cfg) else 'SMTP'}. Check the inbox (and spam)."
    except MailError as e:
        return False, str(e)
