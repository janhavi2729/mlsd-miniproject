"""Real LLM provider adapters (Gemini, OpenAI / OpenAI-compatible) using only the stdlib.

Each adapter sends a system prompt + user message, asks for a JSON object back,
and returns (parsed_json, prompt_tokens, completion_tokens).

Error contract (so the existing retry + circuit breaker logic works unchanged):
- LLMRetryableError (a ConnectionError): timeouts, 429, 5xx, malformed JSON -> retried.
- LLMProviderError (a RuntimeError): auth / bad request / unknown provider -> not retried.
"""

import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

DEFAULT_MODELS = {
    "gemini": "gemini-flash-latest",  # alias: avoids breakage when Google retires a pinned version
    "openai": "gpt-4o-mini",
}

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class LLMRetryableError(ConnectionError):
    """Transient provider failure; safe to retry."""


class LLMProviderError(RuntimeError):
    """Permanent provider failure (bad key, bad request, unsupported provider)."""


def _post_json(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        if e.code == 429 or e.code >= 500:
            raise LLMRetryableError(f"Provider HTTP {e.code}: {detail}") from e
        raise LLMProviderError(f"Provider HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise LLMRetryableError(f"Provider unreachable or timed out: {e}") from e


def parse_json_object(text: str) -> Dict[str, Any]:
    """Parses a JSON object from model output, tolerating ```json fences or leading prose."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LLMRetryableError(f"Model returned invalid JSON: {text[:200]!r}") from e
    if not isinstance(obj, dict):
        raise LLMRetryableError("Model returned JSON that is not an object")
    return obj


def call_gemini(system: str, user: str, model: str, api_key: str, timeout: float) -> Tuple[Dict[str, Any], int, int]:
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
    }
    resp = _post_json(GEMINI_URL.format(model=model), {"x-goog-api-key": api_key}, body, timeout)
    try:
        text = "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError) as e:
        raise LLMRetryableError(f"Unexpected Gemini response shape: {str(resp)[:200]}") from e
    usage = resp.get("usageMetadata", {})
    return parse_json_object(text), int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0))


def call_openai(
    system: str, user: str, model: str, api_key: Optional[str], timeout: float, base_url: Optional[str] = None
) -> Tuple[Dict[str, Any], int, int]:
    url = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    body = {
        "model": model,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    resp = _post_json(url, headers, body, timeout)
    try:
        text = resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LLMRetryableError(f"Unexpected OpenAI response shape: {str(resp)[:200]}") from e
    usage = resp.get("usage", {})
    return parse_json_object(text), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def call_provider(
    provider: str,
    system: str,
    user: str,
    model: str,
    api_key: Optional[str],
    timeout: float,
    base_url: Optional[str] = None,
) -> Tuple[Dict[str, Any], int, int]:
    if provider == "gemini":
        return call_gemini(system, user, model, api_key or "", timeout)
    if provider == "openai":
        return call_openai(system, user, model, api_key, timeout, base_url)
    raise LLMProviderError(f"Unsupported LLM_PROVIDER '{provider}' (use stub, gemini or openai)")
