"""Encryption of secrets at rest (Fernet / AES-128-CBC + HMAC) and log redaction.

The master key lives only in the environment (API_KEY_ENCRYPTION_KEY). In development it falls back to a key derived from
SECRET_KEY so the feature works out of the box; production refuses to store secrets without an explicit master key."""
import base64
import hashlib
import logging
import re

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from backend.app.config import settings
from backend.app.core.exceptions import AppError


class SecretsError(AppError):
    status_code = 503


def _fernet() -> MultiFernet:
    raw = [k.strip() for k in settings.api_key_encryption_key.split(",") if k.strip()]
    if not raw:
        if settings.app_env == "production":
            raise SecretsError("API_KEY_ENCRYPTION_KEY is not configured on the server, so API keys cannot be stored or read.")
        raw = [base64.urlsafe_b64encode(hashlib.sha256(b"datapilot-api-keys:" + settings.secret_key.encode()).digest()).decode()]
    try:
        return MultiFernet([Fernet(k) for k in raw])
    except (ValueError, TypeError) as e:  # never echo the configured value
        raise SecretsError("API_KEY_ENCRYPTION_KEY is invalid: it must be a 32-byte url-safe base64 Fernet key.") from e


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretsError("A stored API key cannot be decrypted with the current API_KEY_ENCRYPTION_KEY (was it changed?). Re-enter the key.") from e


def mask(last4: str) -> str:
    return "•" * 12 + last4 if last4 else ""


_PATTERNS = [re.compile(p) for p in (r"AIza[0-9A-Za-z_\-]{20,}", r"sk-ant-[0-9A-Za-z_\-]{16,}", r"(?i)(x-goog-api-key|x-api-key|authorization)(['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+")]


def redact(text: str) -> str:
    text = _PATTERNS[0].sub("[REDACTED]", text)
    text = _PATTERNS[1].sub("[REDACTED]", text)
    return _PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


class RedactingFilter(logging.Filter):
    """Safety net: scrubs anything that looks like an API key from every log record, including tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = None
            if record.exc_info:
                import traceback

                record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
                record.exc_info = None
        except Exception:  # never let logging break a request
            pass
        return True
