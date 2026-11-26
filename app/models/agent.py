"""models / agent responsibilities."""
from __future__ import annotations

from app.settings_definitions import runtime_limits
from app.agent.state import AgentSettings
from app.agent.state import AgentState
from app.context.conversation import _compact
from app.observability import observation
from app.observability import update as update_observation
from typing import Any
import json
import logging
import os
import requests


logger = logging.getLogger(__name__)


def _ollama_chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, settings: AgentSettings) -> dict[str, Any]:
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    payload: dict[str, Any] = {"model": settings.model, "messages": messages, "stream": False,
                               "think": settings.think,
                               "options": {"temperature": 0, "num_ctx": settings.context_length,
                                           "num_predict": settings.num_predict}}
    if tools:
        payload["tools"] = tools
        _compact(messages)
    response = requests.post(base + "/api/chat", json=payload, timeout=(runtime_limits().http_connect_seconds, runtime_limits().ollama_read_seconds))
    response.raise_for_status()
    return response.json()


def _agent_chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                settings: AgentSettings) -> dict[str, Any]:
    """Call the configured query-agent provider and normalize its response to the Ollama chat shape."""
    if settings.provider == "ollama":
        return _ollama_chat(messages, tools, settings)
    if settings.provider != "openai":
        raise ValueError(f"unsupported query-agent provider {settings.provider!r}")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the OpenAI query agent")
    if tools:
        _compact(messages)
    if settings.reasoning_effort != "none":
        response_input: list[dict[str, Any]] = []
        for item in messages:
            role = item.get("role")
            if role == "tool":
                call_id = item.get("tool_call_id")
                if call_id:
                    response_input.append({"type": "function_call_output", "call_id": call_id,
                                           "output": item.get("content") or ""})
                else:
                    response_input.append({"role": "user", "content": f"Tool result: {item.get('content') or ''}"})
            elif role == "assistant" and item.get("tool_calls"):
                if item.get("content"):
                    response_input.append({"role": "assistant", "content": item["content"]})
                for call in item["tool_calls"]:
                    function = call.get("function") or {}
                    arguments = function.get("arguments") or {}
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    response_input.append({"type": "function_call", "call_id": call.get("id"),
                                           "name": function.get("name"), "arguments": arguments})
            else:
                response_input.append({"role": role, "content": item.get("content") or ""})
        payload: dict[str, Any] = {"model": settings.model, "input": response_input,
                                   "max_output_tokens": settings.num_predict,
                                   "reasoning": {"effort": settings.reasoning_effort}}
        if tools:
            payload["parallel_tool_calls"] = False
            payload["tools"] = [{"type": "function", **(tool.get("function") or {}), "strict": False}
                                for tool in tools]
            payload["tool_choice"] = "auto"
        response = requests.post("https://api.openai.com/v1/responses", json=payload,
                                 headers={"Authorization": f"Bearer {api_key}"}, timeout=(runtime_limits().http_connect_seconds, runtime_limits().openai_responses_read_seconds))
        if not response.ok:
            try:
                detail = (response.json().get("error") or {}).get("message")
            except (ValueError, AttributeError):
                detail = None
            raise RuntimeError(f"OpenAI Responses query-agent request failed (HTTP {response.status_code}): {detail or 'no error detail returned'}")
        result = response.json()
        text_parts: list[str] = []
        normalized_calls = []
        for output in result.get("output") or []:
            if output.get("type") == "function_call":
                try:
                    arguments = json.loads(output.get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                normalized_calls.append({"id": output.get("call_id"), "function": {
                    "name": output.get("name"), "arguments": arguments}})
            elif output.get("type") == "message":
                text_parts.extend(part.get("text", "") for part in output.get("content") or []
                                  if part.get("type") == "output_text")
        usage = result.get("usage") or {}
        input_details = usage.get("input_tokens_details") or {}
        output_details = usage.get("output_tokens_details") or {}
        return {"message": {"content": "".join(text_parts), "tool_calls": normalized_calls},
                "prompt_eval_count": usage.get("input_tokens", 0), "eval_count": usage.get("output_tokens", 0),
                "provider_usage": {"provider": "openai", "model": settings.model,
                                   "prompt_tokens": usage.get("input_tokens", 0),
                                   "completion_tokens": usage.get("output_tokens", 0),
                                   "total_tokens": usage.get("total_tokens", 0),
                                   "cached_prompt_tokens": input_details.get("cached_tokens", 0),
                                   "reasoning_tokens": output_details.get("reasoning_tokens", 0)}}
    payload: dict[str, Any] = {
        "model": settings.model,
        "messages": [],
        "temperature": 0,
        "max_completion_tokens": settings.num_predict,
        # GPT-6 Luna supports Chat Completions tool calling with reasoning disabled.
        "reasoning_effort": "none",
    }
    for item in messages:
        copied = dict(item)
        if copied.get("role") == "assistant" and copied.get("tool_calls"):
            calls = []
            for call in copied["tool_calls"]:
                function = dict(call.get("function") or {})
                arguments = function.get("arguments") or {}
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                function["arguments"] = arguments
                calls.append({"id": call.get("id"), "type": "function", "function": function})
            copied["tool_calls"] = calls
        payload["messages"].append(copied)
    if tools:
        payload["parallel_tool_calls"] = False
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    response = requests.post("https://api.openai.com/v1/chat/completions", json=payload,
                             headers={"Authorization": f"Bearer {api_key}"}, timeout=(runtime_limits().http_connect_seconds, runtime_limits().openai_chat_read_seconds))
    if not response.ok:
        try:
            detail = (response.json().get("error") or {}).get("message")
        except (ValueError, AttributeError):
            detail = None
        raise RuntimeError(f"OpenAI query-agent request failed (HTTP {response.status_code}): {detail or 'no error detail returned'}")
    result = response.json()
    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    normalized_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        normalized_calls.append({"id": call.get("id"), "function": {
            "name": function.get("name"), "arguments": arguments}})
    usage = result.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    return {"message": {"content": message.get("content") or "", "tool_calls": normalized_calls},
            "prompt_eval_count": usage.get("prompt_tokens", 0),
            "eval_count": usage.get("completion_tokens", 0),
            "provider_usage": {"provider": "openai", "model": settings.model,
                               "prompt_tokens": usage.get("prompt_tokens", 0),
                               "completion_tokens": usage.get("completion_tokens", 0),
                               "total_tokens": usage.get("total_tokens", 0),
                               "cached_prompt_tokens": prompt_details.get("cached_tokens", 0),
                               "reasoning_tokens": completion_details.get("reasoning_tokens", 0)}}


def _record_agent_usage(state: AgentState, reply: dict[str, Any], purpose: str) -> dict[str, Any]:
    usage = reply.get("provider_usage") or {
        "provider": state.settings.provider, "model": state.settings.model,
        "prompt_tokens": int(reply.get("prompt_eval_count") or 0),
        "completion_tokens": int(reply.get("eval_count") or 0),
        "total_tokens": int(reply.get("prompt_eval_count") or 0) + int(reply.get("eval_count") or 0),
        "cached_prompt_tokens": 0, "reasoning_tokens": 0,
    }
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = min(prompt, int(usage.get("cached_prompt_tokens") or 0))
    cost = None
    if usage.get("provider") == "openai" and usage.get("model") == "gpt-6-luna":
        cost = ((prompt - cached) * 0.10 + cached * 0.01 + completion * 0.50) / 1_000_000
        cost = round(cost, 10)
    if not state.usage:
        state.usage = {"provider": state.settings.provider, "model": state.settings.model,
                       "reasoning_effort": state.settings.reasoning_effort,
                       "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                       "cached_prompt_tokens": 0, "reasoning_tokens": 0,
                       "estimated_cost_usd": 0.0, "call_details": []}
    state.usage["calls"] += 1
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_prompt_tokens", "reasoning_tokens"):
        state.usage[key] += int(usage.get(key) or 0)
    if cost is not None:
        state.usage["estimated_cost_usd"] = round(state.usage["estimated_cost_usd"] + cost, 10)
    detail = {"purpose": purpose, **usage,
              "reasoning_effort": state.settings.reasoning_effort,
              "endpoint": ("responses" if state.settings.provider == "openai" and state.settings.reasoning_effort != "none"
                           else "chat_completions" if state.settings.provider == "openai" else "ollama"),
              "estimated_cost_usd": cost}
    state.usage["call_details"].append(detail)
    if usage.get("provider") == "openai":
        logger.info("OpenAI query-agent usage purpose=%s model=%s input_tokens=%d output_tokens=%d cached_input_tokens=%d reasoning_tokens=%d estimated_cost_usd=%s",
                    purpose, usage.get("model"), prompt, completion, cached,
                    int(usage.get("reasoning_tokens") or 0), cost)
    return detail


def _tracked_agent_chat(state: AgentState, messages: list[dict[str, Any]],
                        tools: list[dict[str, Any]] | None, purpose: str) -> dict[str, Any]:
    with observation(f"query agent model: {purpose}", as_type="generation",
                     input=json.dumps(messages, ensure_ascii=False),
                     model=state.settings.model,
                     metadata={"provider": state.settings.provider, "purpose": purpose,
                               "reasoning_effort": state.settings.reasoning_effort,
                               "endpoint": "responses" if state.settings.provider == "openai" and state.settings.reasoning_effort != "none" else "chat_completions"}) as generation:
        reply = _agent_chat(messages, tools, state.settings)
        usage = _record_agent_usage(state, reply, purpose)
        message = reply.get("message") or {}
        update_observation(generation,
                           output={"content": (message.get("content") or "")[:2000],
                                   "tool_calls": message.get("tool_calls")},
                           usage_details={"input": usage["prompt_tokens"], "output": usage["completion_tokens"],
                                          "total": usage["total_tokens"]},
                           cost_details=({"input": round((usage["prompt_tokens"] - usage["cached_prompt_tokens"]) * 0.10 / 1_000_000
                                                            + usage["cached_prompt_tokens"] * 0.01 / 1_000_000, 10),
                                         "output": round(usage["completion_tokens"] * 0.50 / 1_000_000, 10),
                                         "total": usage["estimated_cost_usd"]}
                                        if usage["estimated_cost_usd"] is not None else None),
                           metadata={"provider": state.settings.provider, "purpose": purpose,
                                     "reasoning_effort": state.settings.reasoning_effort,
                                     "cached_prompt_tokens": usage["cached_prompt_tokens"],
                                     "reasoning_tokens": usage["reasoning_tokens"]})
    return reply
