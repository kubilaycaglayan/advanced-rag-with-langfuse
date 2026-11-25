"""api / proxy responsibilities."""
from __future__ import annotations

from fastapi import APIRouter
import logging
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
import asyncio
import hmac
import json
import os
import requests

logger = logging.getLogger(__name__)

router = APIRouter()


@router.api_route("/langfuse-ollama/v1/{path:path}", methods=["GET", "POST"])
async def langfuse_ollama_proxy(path: str, request: Request) -> Response:
    """OpenAI-compatible Ollama gateway for Langfuse's local judge calls.

    Qwen3 can spend a short evaluator token budget in its reasoning channel.
    Langfuse's structured judge calls need the final tool output, so ask Ollama
    for no reasoning unless the caller explicitly provides a setting.
    """
    proxy_token = os.getenv("LANGFUSE_OLLAMA_PROXY_TOKEN", "")
    supplied = request.headers.get("authorization", "")
    if not proxy_token or not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], proxy_token):
        raise HTTPException(status_code=401, detail="invalid local model gateway token")
    if path not in {"models", "chat/completions", "embeddings"}:
        raise HTTPException(status_code=404, detail="unsupported Ollama API path")
    if (path == "models" and request.method != "GET") or (path != "models" and request.method != "POST"):
        raise HTTPException(status_code=405, detail="method not allowed")

    body = await request.body()
    if path == "chat/completions":
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                payload.setdefault("reasoning_effort", "none")
                response_schema = payload.get("response_format", {})
                if isinstance(response_schema, dict) and response_schema.get("type") == "json_schema":
                    schema = response_schema.get("json_schema", {}).get("schema")
                    if schema:
                        # Ollama constrains JSON syntax but numeric bounds also need
                        # to be visible to the model, including Langfuse's model probe.
                        payload["messages"] = [
                            {"role": "system", "content": "Return JSON matching this schema exactly. Respect numeric minimum/maximum and required fields: " + json.dumps(schema)},
                            *payload.get("messages", []),
                        ]
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                response_format = payload.get("response_format")
                response_format_type = response_format.get("type") if isinstance(response_format, dict) else response_format
                logger.info("Local judge request model=%s response_format=%s tools=%d reasoning_effort=%s max_tokens=%s",
                            payload.get("model"), response_format_type,
                            len(payload.get("tools") or []), payload.get("reasoning_effort"), payload.get("max_tokens"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    headers = {"Accept": request.headers.get("accept", "application/json")}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    upstream = await asyncio.to_thread(
        requests.request,
        request.method,
        f"{base_url}/v1/{path}",
        params=request.query_params,
        headers=headers,
        data=body or None,
        timeout=(10, 300),
        stream=True,
    )
    response_headers = {}
    if upstream.headers.get("content-type"):
        response_headers["Content-Type"] = upstream.headers["content-type"]
    if "text/event-stream" in upstream.headers.get("content-type", ""):
        return StreamingResponse(upstream.iter_content(chunk_size=None), status_code=upstream.status_code,
                                 headers=response_headers, background=BackgroundTask(upstream.close))
    content = await asyncio.to_thread(lambda: upstream.content)
    if path == "chat/completions":
        try:
            result = json.loads(content)
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            logger.info("Local judge response status=%d finish=%s tool_calls=%d content_chars=%d",
                        upstream.status_code, choice.get("finish_reason"), len(message.get("tool_calls") or []),
                        len(message.get("content") or ""))
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, AttributeError):
            logger.info("Local judge response status=%d non_json_body_chars=%d", upstream.status_code, len(content))
    upstream.close()
    return Response(content=content, status_code=upstream.status_code, headers=response_headers)

