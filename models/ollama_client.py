"""Klient lokalnej Ollamy: żądanie JSON do /api/generate przez stdlib urllib."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_MODEL = "qwen3:1.7b"
DEFAULT_HOST = "http://localhost:11434"
TIMEOUT_S = 30

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)

# Structured outputs (Ollama ≥0.5): sztywny kształt odpowiedzi modelu.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "device": {"type": "string"},
                    "to": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["device", "to", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["choices"],
    "additionalProperties": False,
}


def _request(base: str, payload: dict) -> tuple[dict | None, int | None]:
    """Jedno wywołanie /api/generate; zwraca (sparsowany JSON albo None, kod HTTP błędu)."""
    request = Request(
        f"{base}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            outer = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(outer["response"])
    except HTTPError as exc:
        return None, exc.code
    except (
        URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ):
        return None, None
    return (parsed, None) if isinstance(parsed, dict) else (None, None)


def generate(prompt: str, *, model: str | None = None, host: str | None = None) -> dict | None:
    """Wysyła prompt do Ollamy; zwraca sparsowany JSON modelu albo None przy każdym błędzie.

    Żądanie niesie JSON Schema w polu `format`; gdy serwer odrzuci schema
    (HTTP 400), ponawia raz ze zwykłym "json".
    """
    base = (host or OLLAMA_HOST).rstrip("/")
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "format": RESPONSE_SCHEMA,
        "stream": False,
    }
    result, status = _request(base, payload)
    if result is None and status == 400:
        result, _ = _request(base, {**payload, "format": "json"})
    return result
