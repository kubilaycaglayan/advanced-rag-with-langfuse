"""Execute the resolved agent pipeline with one result contract."""
from __future__ import annotations

import time
from typing import Any, Callable

from app.corpus_profiles import agent_prompt
from app.agent.runner import run_agent
from app.agent.execution import run_agent as run_graph_agent
from app.pipelines.execution_identity import execution_backend
from app.pipelines.resolver import ResolvedRun


def execute_question(question: str, resolved: ResolvedRun, collection: str,
        on_token: Callable[[str], None] | None = None, on_status: Callable[[str], None] | None = None) -> dict[str, Any]:
    def on_event(event: dict[str, Any]) -> None:
        if on_status and event.get("type") == "tool":
            on_status(f"searching · {event.get('name')}")
        elif on_status and event.get("type") == "turn":
            on_status("thinking")

    system_prompt = None
    if resolved.corpus_id != "millennium":
        system_prompt = agent_prompt()
    selected_runner = run_graph_agent if execution_backend(resolved) == "langgraph" else run_agent
    agent = selected_runner(question, collection, resolved.config,
                      settings=resolved.agent_settings, on_event=on_event,
                      system_prompt=system_prompt)
    evidence = list(agent.get("evidence") or [])
    citations = [label if str(label).startswith("[") else f"[{label}]" for label in agent.get("citations") or []]
    if on_status:
        on_status("answering")
    if on_token:
        words = agent["answer"].split(" ")
        for index, word in enumerate(words):
            on_token(word + (" " if index < len(words) - 1 else ""))
            if index < len(words) - 1:
                time.sleep(0.04)
    result = {"question": question, "answer": agent["answer"], "citations": citations,
              "reranked": evidence, "candidates": evidence, "baseline": [],
              "evidence": "\n\n".join(f"[E{position}] {row.get('text', '')}" for position, row in enumerate(evidence, 1)),
              "generated_queries": [call.get("arguments", {}).get("query") for call in agent.get("trace", [])
                                    if call.get("arguments", {}).get("query")],
              "timings": {"agent_seconds": agent.get("latency_seconds")},
              "latency_seconds": agent.get("latency_seconds"),
              "generation_model": resolved.config.generation_model.name,
              "agent_provider": resolved.agent_settings.provider,
              "agent_model": agent.get("model", resolved.agent_settings.model),
              "agent_usage": agent.get("usage", {}),
              "engine": "agent", "mode": "agent", "tool_calls": agent.get("tool_calls"),
              "agent_stopped": agent.get("stopped"), "agent_trace": agent.get("trace", []),
              "answer_thinking": None, "translated_question": None,
              "name_completed_question": None, "low_confidence": None}
    result.update(resolved.version_fields)
    return result
