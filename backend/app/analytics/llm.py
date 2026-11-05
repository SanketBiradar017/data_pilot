"""Optional LLM access. Returns None when no provider is configured, a usage cap is hit, or the call fails,
so every caller must have a deterministic fallback.

Provider/model/temperature/limits are admin-editable at runtime (appconfig "ai"); API keys stay in the environment."""
import logging
from datetime import UTC, datetime, timedelta

import httpx

from backend.app.config import settings

log = logging.getLogger(__name__)

_DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "google": "gemini-2.0-flash"}


def _key(provider: str) -> str:
    return {"anthropic": settings.anthropic_api_key, "google": settings.google_api_key}.get(provider, "")


def ai_runtime() -> dict:
    from backend.app.services import appconfig

    c = appconfig.get("ai")
    provider = c["provider"] or settings.llm_provider
    model = c["model"] or (settings.llm_model if provider == settings.llm_provider else "") or _DEFAULT_MODELS.get(provider, "")
    return {"provider": provider, "model": model, "enabled": bool(_key(provider)), "cfg": c}


def _record(provider: str, model: str, tin: int, tout: int, ok: bool) -> None:
    try:
        from backend.app.core.security import current_user_id
        from backend.app.db.session import SessionLocal
        from backend.app.models import LlmUsage

        with SessionLocal() as db:
            db.add(LlmUsage(user_id=current_user_id.get(), provider=provider, model=model,
                            input_tokens=tin, output_tokens=tout, ok=ok))
            db.commit()
    except Exception:
        log.warning("llm usage log failed", exc_info=True)


def _over_cap(cfg: dict) -> str | None:
    """Admin-configured spend guards (global, all users)."""
    if not (cfg.get("monthly_token_cap") or cfg.get("daily_call_cap")):
        return None
    try:
        from sqlalchemy import func, select

        from backend.app.db.session import SessionLocal
        from backend.app.models import LlmUsage

        now = datetime.now(UTC)
        with SessionLocal() as db:
            if cfg.get("monthly_token_cap"):
                used = db.scalar(select(func.coalesce(func.sum(LlmUsage.input_tokens + LlmUsage.output_tokens), 0)).where(
                    LlmUsage.created_at >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)))
                if used >= cfg["monthly_token_cap"]:
                    return "monthly token cap reached"
            if cfg.get("daily_call_cap"):
                calls = db.scalar(select(func.count(LlmUsage.id)).where(LlmUsage.created_at >= now - timedelta(days=1)))
                if calls >= cfg["daily_call_cap"]:
                    return "daily call cap reached"
    except Exception:
        log.warning("cap check failed", exc_info=True)
    return None


def _call(provider: str, model: str, system: str, prompt: str, max_tokens: int, temperature: float) -> str:
    if provider == "anthropic":
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": _key(provider), "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                  "system": system, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        u = body.get("usage") or {}
        _record(provider, model, u.get("input_tokens", 0), u.get("output_tokens", 0), True)
        return "".join(b.get("text", "") for b in body["content"]).strip()
    if provider == "google":
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": _key(provider)},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        u = body.get("usageMetadata") or {}
        _record(provider, model, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), True)
        return body["candidates"][0]["content"]["parts"][0]["text"].strip()
    raise ValueError(f"unknown provider {provider}")


def llm_complete(system: str, prompt: str, max_tokens: int = 1200) -> str | None:
    rt = ai_runtime()
    if not rt["enabled"]:
        return None
    cfg = rt["cfg"]
    if (why := _over_cap(cfg)):
        log.warning("LLM skipped: %s", why)
        return None
    if cfg.get("system_prompt"):
        system = f"{system}\n\n{cfg['system_prompt']}"
    if cfg.get("max_output_tokens"):
        max_tokens = min(max_tokens, int(cfg["max_output_tokens"]))
    temp = cfg["temperature"] if cfg.get("temperature") is not None else settings.llm_temperature

    attempts = [(rt["provider"], rt["model"])]
    fp, fm = cfg.get("fallback_provider"), cfg.get("fallback_model")
    if fp and _key(fp) and (fp, fm or _DEFAULT_MODELS.get(fp, "")) != attempts[0]:
        attempts.append((fp, fm or _DEFAULT_MODELS.get(fp, "")))
    for provider, model in attempts:
        try:
            return _call(provider, model, system, prompt, max_tokens, temp)
        except Exception as e:  # network, quota, malformed response -> try fallback model
            log.warning("LLM call failed (%s/%s): %s", provider, model, e)
            _record(provider, model, 0, 0, False)
    return None
