"""Optional LLM access. Returns None when no provider is configured or the call fails,
so every caller must have a deterministic fallback."""
import logging

import httpx

from backend.app.config import settings

log = logging.getLogger(__name__)

_DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "google": "gemini-2.0-flash"}


def llm_complete(system: str, prompt: str, max_tokens: int = 1200) -> str | None:
    if not settings.llm_enabled:
        return None
    provider = settings.llm_provider
    model = settings.llm_model or _DEFAULT_MODELS.get(provider, "")
    try:
        if provider == "anthropic":
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": max_tokens, "temperature": settings.llm_temperature,
                      "system": system, "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"]).strip()
        if provider == "google":
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": settings.google_api_key},
                json={"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": settings.llm_temperature, "maxOutputTokens": max_tokens}},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:  # network, quota, malformed response
        log.warning("LLM call failed (%s): %s", provider, e)
    return None
