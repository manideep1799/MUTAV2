from __future__ import annotations
import json
import time
from openai import OpenAI
from config import settings

_client: OpenAI | None = None


def _get() -> OpenAI:
    global _client
    if _client is None:
        if settings.OLLAMA_BASE_URL:
            _client = OpenAI(
                api_key="ollama",
                base_url=settings.OLLAMA_BASE_URL,
                timeout=120.0,
                default_headers={"ngrok-skip-browser-warning": "true"},
            )
        else:
            _client = OpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
                timeout=120.0,
            )
    return _client


MAX_RETRIES = 10


def complete(prompt: str, *, temperature: float = 0.2, max_tokens: int = 1024, json_mode: bool = False) -> tuple[str, float]:
    """Single-turn completion. Returns (text, latency_ms).

    Retries on rate limits with exponential backoff.
    """
    t0 = time.perf_counter()
    for attempt in range(MAX_RETRIES):
        try:
            kwargs = {
                "model": settings.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            resp = _get().chat.completions.create(**kwargs)
            latency_ms = (time.perf_counter() - t0) * 1000
            return resp.choices[0].message.content or "", latency_ms
        except Exception as exc:  # noqa: BLE001
            transient = type(exc).__name__ in (
                "RateLimitError", "APIConnectionError", "APITimeoutError",
                "InternalServerError",
            )
            if not transient or attempt == MAX_RETRIES - 1:
                raise
            wait = _retry_after(exc) or (2 ** attempt)
            print(f"    [{type(exc).__name__}] retrying in {wait:.0f}s "
                  f"({attempt + 1}/{MAX_RETRIES - 1})", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _retry_after(exc: Exception) -> float | None:
    """Seconds the server asked us to wait, if it said."""
    resp = getattr(exc, "response", None)
    header = getattr(resp, "headers", {}) or {}
    for key in ("retry-after", "x-ratelimit-reset-requests"):
        raw = header.get(key)
        if raw:
            try:
                return min(float(str(raw).rstrip("s")), 60.0)
            except ValueError:
                pass
    return None


def extract_json(text: str) -> dict | None:
    """Best-effort JSON object out of a model response.

    Handles fenced blocks, leading prose, and trailing commentary.
    Returns None rather than raising; the caller decides what a failed
    extraction means for it.
    """
    s = text.strip()
    if s.startswith("```"):
        stripped = "\n".join(s.split("\n")[1:])
        s = stripped[:-3] if stripped.rstrip().endswith("```") else stripped
        s = s.strip()
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to the outermost brace pair
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(s[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def json_complete(prompt: str, *, temperature: float = 0.1, max_tokens: int = 1024) -> tuple[dict | list, str, float]:
    """Complete and parse JSON. Returns (parsed, raw_text, latency_ms).
    Raises ValueError if the response is not extractable as JSON."""
    text, latency_ms = complete(prompt, temperature=temperature, max_tokens=max_tokens, json_mode=True)
    parsed = extract_json(text)
    if parsed is None:
        raise ValueError(f"could not extract JSON from model output: {text[:200]!r}")
    return parsed, text, latency_ms
