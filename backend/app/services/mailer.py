import logging
import smtplib
from email.message import EmailMessage

from backend.app.config import settings
from backend.app.services import appconfig

log = logging.getLogger("datapilot.mail")


class _SafeDict(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def render(template: str, **kw) -> str:
    return template.format_map(_SafeDict(**kw))


def send_mail(to: str, subject: str, body: str) -> tuple[bool, str]:
    """Best-effort SMTP send. Returns (ok, error). Never raises."""
    c = appconfig.get("smtp")
    if not (c["host"] and c["from_email"]):
        return False, "SMTP is not configured"
    msg = EmailMessage()
    msg["From"] = f'{c["from_name"]} <{c["from_email"]}>' if c["from_name"] else c["from_email"]
    msg["To"], msg["Subject"] = to, subject.replace("\n", " ")[:200]
    msg.set_content(body)
    try:
        with smtplib.SMTP(c["host"], int(c["port"]), timeout=10) as s:
            if c["use_tls"]:
                s.starttls()
            if c["username"] and settings.smtp_password:
                s.login(c["username"], settings.smtp_password)
            s.send_message(msg)
        return True, ""
    except Exception as e:  # noqa: BLE001
        log.warning("mail to %s failed: %s", to, e)
        return False, f"{type(e).__name__}: {e}"[:300]
