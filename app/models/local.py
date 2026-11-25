"""models / local responsibilities."""
from __future__ import annotations

from app.observability import observation as _observe
from app.observability import update as _update
import os
import requests


def local_generate(messages: list[dict[str, str]], model: str, budgets: tuple[int, ...],
            temperature: float = 0, context_length: int = 8192, *,
            name: str = "answer generation") -> str:
    """Non-streaming local generation for query transformations and scene selection."""
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    keep_alive: str | int = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
    if keep_alive.lstrip("-").isdigit():
        keep_alive = int(keep_alive)
    last_error: Exception | None = None
    with _observe(name, as_type="generation", input=messages, model=model) as obs:
        for budget in budgets:
            try:
                response = requests.post(f"{base}/api/chat", json={
                    "model": model, "keep_alive": keep_alive, "messages": messages,
                    "think": False, "stream": False,
                    "options": {"temperature": temperature, "num_ctx": context_length, "num_predict": budget},
                }, timeout=(10, 900), stream=False)
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})
                text, thinking = message.get("content", "").strip(), message.get("thinking")
                if text:
                    _update(obs, output=text,
                            usage_details={"input": data.get("prompt_eval_count"), "output": data.get("eval_count")},
                            **({"metadata": {"thinking": thinking}} if thinking else {}))
                    return text
            except requests.RequestException as exc:
                last_error = exc
                break
        raise RuntimeError(f"Ollama request failed or returned empty content: {last_error or 'empty response'}")
