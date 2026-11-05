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
    """Current API key: the active admin-managed key if any, else the environment key. Resolved per call, so changes apply live."""
    from backend.app.services import ai_config

    return ai_config.resolve(provider).key


def ai_runtime() -> dict:
    from backend.app.services import appconfig

    c = appconfig.get("ai")
    provider = c["provider"] or settings.llm_provider
    if provider in ("", "none"):  # env says "no LLM", but an admin may have activated a key: that wins
        from backend.app.services import ai_config

        provider = next((p for p in ai_config.PROVIDERS if ai_config.resolve(p).source == "admin"), provider)
    model = c["model"] or (settings.llm_model if provider == settings.llm_provider else "") or _DEFAULT_MODELS.get(provider, "")
    from backend.app.services import ai_config

    if model and not ai_config.usable_model(model):  # e.g. an API key pasted into LLM_MODEL: never send or display it
        log.warning("Configured model name is not a valid model id (ignored, using the default). Check LLM_MODEL / the AI settings.")
        model = _DEFAULT_MODELS.get(provider, "")
    return {"provider": provider, "model": model, "enabled": bool(_key(provider)), "cfg": c}


def _record(provider: str, model: str, tin: int, tout: int, ok: bool, key_id: int | None = None) -> None:
    try:
        from backend.app.core.security import current_user_id
        from backend.app.db.session import SessionLocal
        from backend.app.models import LlmUsage

        with SessionLocal() as db:
            db.add(LlmUsage(user_id=current_user_id.get(), provider=provider, model=model,
                            input_tokens=tin, output_tokens=tout, ok=ok, api_key_id=key_id))
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
    from backend.app.services import ai_config

    rk = ai_config.resolve(provider)   # fetched fresh for every request
    if not rk.key:
        raise ValueError(f"no API key for {provider}")
    if provider == "anthropic":
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": rk.key, "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                  "system": system, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        u = body.get("usage") or {}
        _record(provider, model, u.get("input_tokens", 0), u.get("output_tokens", 0), True, rk.key_id)
        return "".join(b.get("text", "") for b in body["content"]).strip()
    if provider == "google":
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": rk.key},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        u = body.get("usageMetadata") or {}
        _record(provider, model, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), True, rk.key_id)
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
            # log only the exception class and HTTP status: provider error bodies/URLs are never written
            status = getattr(getattr(e, "response", None), "status_code", None)
            log.warning("LLM call failed (%s/%s): %s%s", provider, model, type(e).__name__, f" HTTP {status}" if status else "")
            _record(provider, model, 0, 0, False, ai_config_key_id(provider))
    return None


def ai_config_key_id(provider: str) -> int | None:
    from backend.app.services import ai_config

    return ai_config.resolve(provider).key_id
