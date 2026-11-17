"""Send an approved quotation by email (SMTP). Only called after a human approves and clicks Send."""
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


class MailError(Exception):
    pass


def valid_email(addr: str) -> bool:
    return bool(addr) and len(addr) <= 254 and bool(EMAIL_RE.match(addr)) and "\n" not in addr and "\r" not in addr


def mail_enabled(cfg) -> bool:
    return bool(cfg.get("SMTP_HOST") and cfg.get("SMTP_USER") and cfg.get("SMTP_PASSWORD"))


def send_quote_email(cfg, *, to, company_name, reply_to, subject, body, pdf_bytes, pdf_name):
    if not mail_enabled(cfg):
        raise MailError("Email is not set up on this server (SMTP settings are missing).")
    if not valid_email(to):
        raise MailError("The customer email address is not valid.")
    sender = cfg.get("SMTP_FROM") or cfg["SMTP_USER"]
    msg = EmailMessage()
    msg["From"] = formataddr((company_name.replace("\n", " ")[:80], sender))
    msg["To"] = to
    if reply_to and valid_email(reply_to):
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject.replace("\n", " ")[:200]
    msg.set_content(body)
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=pdf_name)
    try:
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
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"The email could not be sent ({type(e).__name__}). Check the SMTP settings.")


def send_notice(cfg, *, to, subject, body):
    """Short plain-text notice to the business owner (e.g. 'customer accepted'). Never raises."""
    if not mail_enabled(cfg) or not valid_email(to):
        return False
    msg = EmailMessage()
    msg["From"] = cfg.get("SMTP_FROM") or cfg["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = subject.replace("\n", " ")[:200]
    msg.set_content(body)
    try:
        mode = cfg.get("SMTP_SECURITY", "starttls")
        smtp = (smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15, context=ssl.create_default_context())
                if mode == "ssl" else smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15))
        with smtp:
            if mode == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        return False
