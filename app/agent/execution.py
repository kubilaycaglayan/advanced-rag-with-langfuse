"""Unregistered v2.17 execution boundaries and graph-backed agent entry point."""
from __future__ import annotations

from app.agent.prechecks import _connection_precheck
from app.agent.prechecks import _moment_message
from app.agent.prechecks import _moment_precheck
from app.agent.prechecks import _normalize_question
from app.agent.prechecks import _precheck_message
from app.agent.prechecks import _premise_probe
from app.agent.prechecks import _sequence_message
from app.agent.prechecks import _sequence_precheck
from app.agent.prechecks import _true_account_message
from app.agent.prechecks import _true_account_precheck
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.protocol import _clip
from app.agent.protocol import _parse_text_tool
from app.agent.schemas import _tool_specs
from app.settings_definitions import runtime_limits
from app.agent.state import AgentSettings
from app.agent.submission import _answer_key
from app.agent.submission import prepare_final_answer
from app.agent.submission import draft_budget_answer
from app.agent.submission import _search_progress_hint
from app.agent.submission import _verify_submission
from app.agent.tools.coverage import _coverage_gap
from app.agent.tools.dispatch import _run_tool
from app.agent.tools.scenes import _initial_scene_message
from app.agent.tools.scenes import _initial_scene_probe
from app.models.agent import _tracked_agent_chat
from app.observability import observation
from app.observability import update as update_observation
from app.pipelines.config import ResolvedPipelineConfig
from typing import Any
from typing import Callable
import json
import re
import time

from app.agent.state import ExecutionState, AgentRuntime
from app.settings_definitions import TargetAgentSettings


def prepare_question(state: ExecutionState, runtime: AgentRuntime) -> None:
    """Normalize and gather initial evidence in released execution order."""
    normalized, name_notes = _normalize_question(state)
    state.question = normalized
    state.name_notes = name_notes
    with observation("connection pre-check", input=state.question):
        precheck = _connection_precheck(state)
    state.messages = [{"role": "system", "content": state.system_prompt},
                                      {"role": "user", "content": normalized}]
    messages = state.messages
    if state.settings.initial_scene_probe:
        started_probe = time.perf_counter()
        with observation("initial scene probe", input=state.question) as probe_observation:
            scene, probe_error = _initial_scene_probe(state)
            update_observation(probe_observation,
                               output={"scene": scene, "error": probe_error or None})
        if scene:
            messages.append({"role": "user", "content": _initial_scene_message(scene)})
        state.trace.append({"tool": "initial scene probe", "arguments": {"query": state.question},
                            "seconds": round(time.perf_counter() - started_probe, 2),
                            "error": probe_error or None,
                            "result_ids": scene["passage_ids"] if scene else [],
                            "scene_id": scene["scene_id"] if scene else None})
    if precheck:
        messages.append({"role": "user", "content": _precheck_message(precheck)})
        state.trace.append({"tool": "connection pre-check", "arguments": {"person_a": precheck["person_a"],
                                                                          "person_b": precheck["person_b"]},
                            "seconds": 0.0, "error": None, "result_ids": [row["passage_ids"][0] for row in precheck["facts"] if row["passage_ids"]]})
    with observation("true account pre-check", input=state.question):
        true_check = _true_account_precheck(state)
    if true_check:
        messages.append({"role": "user", "content": _true_account_message(true_check)})
        state.trace.append({"tool": "true account pre-check",
                            "arguments": {"person": true_check["person"], "event": true_check["event"],
                                          "other_people": true_check.get("other_people")},
                            "seconds": 0.0, "error": None,
                            "result_ids": [row["id"] for row in (true_check.get("passages") or [])]})
    with observation("sequence pre-check", input=state.question):
        sequence_check = _sequence_precheck(state)
    if sequence_check:
        messages.append({"role": "user", "content": _sequence_message(sequence_check)})
        state.trace.append({"tool": "sequence pre-check", "arguments": {"question": state.question},
                            "seconds": 0.0, "error": None,
                            "result_ids": [row["id"][:8] for row in (sequence_check.get("scene_passages") or [])]})
    with observation("moment pre-check", input=state.question):
        moment_check = _moment_precheck(state)
    if moment_check:
        messages.append({"role": "user", "content": _moment_message(moment_check)})
        state.trace.append({"tool": "moment pre-check", "arguments": {"question": state.question},
                            "seconds": 0.0, "error": None,
                            "result_ids": [row["id"][:8] for row in (moment_check.get("keywords") or [])[:3]
                                           + (moment_check.get("scene_rows") or [])[:6]]})
    with observation("premise probe", input=state.question) as premise_observation:
        premise_message = _premise_probe(state)
        update_observation(premise_observation, output={"passage_ids": state.premise_evidence})
    if premise_message:
        messages.append({"role": "user", "content": premise_message})
        state.trace.append({"tool": "premise probe", "arguments": {"question": state.question},
                            "seconds": 0.0, "error": None, "result_ids": state.premise_evidence})
    state.route = "decide"


def select_model_turn(state: ExecutionState, runtime: AgentRuntime) -> None:
    """Run one model-selection turn and expose the pending reply."""
    messages = state.messages
    settings = state.settings
    turn = state.turns
    started = time.perf_counter()
    with observation(f"agent turn {turn}", as_type="span", input=messages[-2:],
                     metadata={"provider": settings.provider, "model": settings.model}) as turn_obs:
        reply = _tracked_agent_chat(state, messages, runtime.tool_specs, "tool selection and answer")
        message = reply.get("message") or {}
        update_observation(turn_obs, output={"content": (message.get("content") or "")[:2000],
                                             "tool_calls": message.get("tool_calls"),
                                             "usage": reply.get("provider_usage")})
    content = (message.get("content") or "").strip()
    calls = list(message.get("tool_calls") or [])
    if not calls:
        parsed = _parse_text_tool(content)
        if parsed:
            calls = [{"function": {"name": parsed[0], "arguments": parsed[1]}}]
    runtime.emit({"type": "turn", "turn": turn, "seconds": round(time.perf_counter() - started, 2),
          "content": content[:1000], "tool_calls": [call.get("function", {}).get("name") for call in calls]})
    state.pending_reply = reply
    state.pending_content = content
    state.pending_calls = calls
    state.next_tool_index = 0
    state.verification_supported = None
    state.verification_reason = ""
    state.route = "tools" if calls else "review"


def review_answer_text(state: ExecutionState, runtime: AgentRuntime) -> None:
    """Apply the existing no-tool review and feedback order."""
    messages = state.messages
    content = state.pending_content
    turn = state.turns
    state.route = "decide"
    # A final answer without submit_answer is accepted only when it cites collected passage ids.
    ids = [short.casefold() for short in re.findall(r"\[([0-9a-fA-F]{8})\]", content)
           if short.casefold() in state.evidence]
    ids = list(dict.fromkeys(ids))
    if _answer_key(content) in state.rejected_answers:
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "That central answer was already rejected. Resolve the contradiction or give a different, supported answer."})
        return
    if state.tool_calls < state.settings.min_tool_calls and state.nudges < runtime_limits().nudge_limit:
        state.nudges += 1
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": (
            f"You have made {state.tool_calls} tool calls; investigate more before answering (at least "
            f"{state.settings.min_tool_calls}). Check each part of the question and search for the part the "
            "passages do not yet state.")})
        with observation("minimum tool nudge", input={"turn": turn}):
            runtime.emit({"type": "nudge", "turn": turn})
        return
    if state.evidence:
        with observation("coverage check", input=content):
            gap = _coverage_gap(state, content)
        if gap:
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "tool", "content": _clip(gap)})
            runtime.emit({"type": "coverage", "covered": gap.get("covered_stages"),
                  "people": gap.get("people_involved")})
            return
    if ids:
        focus = list(dict.fromkeys([*state.premise_evidence, *state.focus]))
        focus = [short for short in focus if short not in ids][:6]
        with observation("submission verification", input={"answer": content, "ids": ids}) as verification_obs:
            supported, reason = _verify_submission(state, content, ids, focus)
            update_observation(verification_obs, output={"supported": supported, "reason": reason},
                               level="DEFAULT" if supported else "WARNING")
        state.verification_supported, state.verification_reason = supported, reason
        runtime.emit({"type": "verify", "supported": supported, "reason": reason})
        if not supported:
            state.rejected_answers.add(_answer_key(content))
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "tool", "content": _clip({
                "error": "the answer is not supported by the cited passages", "reason": reason,
                "note": "search again: find a passage that names the person and states the answer, then submit"})})
            return
    if not ids and state.nudges < runtime_limits().nudge_limit:
        state.nudges += 1
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": (
            "You did not call a tool. If you have enough evidence, call submit_answer with the answer and the "
            "8-character passage_ids it relies on; otherwise continue searching.")})
        with observation("no tool nudge", input={"turn": turn}):
            runtime.emit({"type": "nudge", "turn": turn})
        return
    if not ids:
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "Submit a supported answer with passage IDs, or say the evidence is insufficient."})
        return
    state.candidate_answer = content
    state.candidate_passage_ids = ids
    state.candidate_stopped = "content"
    state.candidate_raw_answer = None
    state.route = "final"


def process_reply_tools(state: ExecutionState, runtime: AgentRuntime) -> None:
    """Process the entire reply sequentially, retaining rejection continue semantics."""
    messages = state.messages
    settings = state.settings
    turn = state.turns
    calls = state.pending_calls
    content = state.pending_content
    state.route = "decide"
    for index, call in enumerate(calls):
        if not call.get("id"):
            call["id"] = f"agent_{turn}_{index + 1}"
    messages.append({"role": "assistant", "content": content,
                     "tool_calls": [{"id": call.get("id"), "function": {"name": call.get("function", {}).get("name"),
                                                                       "arguments": call.get("function", {}).get("arguments", {})}}
                                    for call in calls]})
    for call in calls[state.next_tool_index:]:
        state.next_tool_index += 1
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        state.tool_calls += 1
        started = time.perf_counter()
        with observation(f"tool: {name}", as_type="tool", input=arguments) as tool_obs:
            try:
                payload, stop = _run_tool(state, name, arguments)
            except Exception as exc:  # a tool failure is an observation the agent can recover from
                payload, stop = {"error": f"{type(exc).__name__}: {exc}"}, False
            update_observation(tool_obs, output=payload,
                               level="ERROR" if isinstance(payload, dict) and payload.get("error") else "DEFAULT",
                               status_message=payload.get("error") if isinstance(payload, dict) else None)
        seconds = round(time.perf_counter() - started, 2)
        state.trace.append({"tool": name, "arguments": arguments, "seconds": seconds,
                            "error": payload.get("error") if isinstance(payload, dict) else None,
                            "result_ids": [hit.get("id") for hit in (payload.get("hits") or [])] if isinstance(payload, dict) else []})
        runtime.emit({"type": "tool", "name": name, "arguments": arguments, "seconds": seconds,
              "error": payload.get("error") if isinstance(payload, dict) else None})
        progress_hint = (_search_progress_hint(state, name, arguments, payload)
                         if isinstance(payload, dict) else None)
        if stop and _answer_key(payload["raw_answer"]) in state.rejected_answers:
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _clip({
                "error": "this answer was already rejected; resolve its unsupported claim before submitting again"})})
            continue
        if name == "find_names" and payload.get("likely") and payload.get("name") not in state.resolved_names:
            state.resolved_names.add(payload["name"])
            with observation("name check message", input=payload):
                messages.append({"role": "user", "content": (
                    f"Name check: the books do not use {payload['name']!r}; the person meant is {payload['likely']}. "
                    "Continue the question with that name; do not answer that the character does not exist.")})
        if stop:
            if payload["passage_ids"]:
                focus = list(dict.fromkeys([*state.premise_evidence, *state.focus]))
                focus = [short for short in focus if short not in payload["passage_ids"]][:6]
                with observation("submission verification", input=payload) as verification_obs:
                    supported, reason = _verify_submission(state, payload["raw_answer"], payload["passage_ids"], focus)
                    update_observation(verification_obs, output={"supported": supported, "reason": reason},
                                       level="DEFAULT" if supported else "WARNING")
                state.verification_supported, state.verification_reason = supported, reason
                runtime.emit({"type": "verify", "supported": supported, "reason": reason})
                if not supported:
                    state.rejected_answers.add(_answer_key(payload["raw_answer"]))
                    messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _clip({
                        "error": "the answer is not supported by the cited passages",
                        "reason": reason,
                        "note": "search again: find a passage that states the answer, then submit a corrected answer"})})
                    continue
            state.candidate_answer = payload["answer"]
            state.candidate_passage_ids = payload["passage_ids"]
            state.candidate_raw_answer = payload.get("raw_answer")
            state.candidate_stopped = "submit"
            state.submitted_payload = payload
            state.route = "final"
            return
        messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": _clip(payload)})
        if progress_hint:
            messages.append({"role": "user", "content": progress_hint})
            state.trace.append({"tool": "progress nudge", "arguments": {"query": arguments.get("query")},
                                "seconds": 0.0, "error": None, "result_ids": []})
        if state.tool_calls >= settings.max_tool_calls:
            runtime.emit({"type": "tool_budget"})
            state.budget_reason = "tool_budget"
            state.route = "budget"
            return


def decide_next_turn(state: ExecutionState, runtime: AgentRuntime) -> None:
    """Retain application budgets, including the timeout turn counter semantics."""
    if state.turns >= state.settings.max_turns:
        state.budget_reason = "turn_budget"
        state.route = "budget"
        runtime.emit({"type": "turn_budget"})
        return
    state.turns += 1
    if time.perf_counter() - state.started > state.settings.timeout_seconds:
        state.budget_reason = "timeout"
        state.route = "budget"
        runtime.emit({"type": "timeout"})
        return
    state.route = "select"


def draft_budget(state: ExecutionState, runtime: AgentRuntime) -> None:
    """Create one handoff draft; route to shared final preparation without calling it."""
    if state.budget_drafted:
        return
    with observation("forced answer", input={"reason": state.budget_reason}):
        content, ids = draft_budget_answer(state, state.messages)
    state.candidate_answer = content
    state.candidate_passage_ids = ids
    state.candidate_raw_answer = None
    state.candidate_stopped = "budget"
    state.budget_drafted = True
    state.route = "final"


def finalize_answer(state: ExecutionState, runtime: AgentRuntime) -> None:
    """Apply the current repair/synthesis rules once and retain the final result."""
    if state.final_prepared:
        return
    result = prepare_final_answer(state, state.candidate_answer, state.candidate_passage_ids,
                                  stopped=state.candidate_stopped, raw_answer=state.candidate_raw_answer)
    if state.submitted_payload is not None:
        result["submitted"] = state.submitted_payload
    state.final_result = result
    state.final_prepared = True
    state.route = "done"
    update_observation(runtime.root_observation, output=result)


def run_agent(question: str, collection: str, config: ResolvedPipelineConfig | None = None, *,
              settings: TargetAgentSettings | None = None,
              on_event: Callable[[dict[str, Any]], None] | None = None,
              system_prompt: str | None = None) -> dict[str, Any]:
    """Answer through the custom v2.17 graph without changing released application routing."""
    if not question.strip():
        raise ValueError("question must not be blank")
    if settings is not None and (not isinstance(settings, TargetAgentSettings) or isinstance(settings, AgentSettings)):
        raise ValueError("target execution requires TargetAgentSettings without the legacy early-stop option")
    settings = settings or TargetAgentSettings()
    state = ExecutionState(question=question, asked=question, collection=collection,
                           config=config or ResolvedPipelineConfig(), settings=settings,
                           system_prompt=system_prompt or SYSTEM_PROMPT, started=time.perf_counter())
    runtime = AgentRuntime(on_event=on_event)
    from app.agent.graph import invoke_graph
    with observation("agent run", input={"question": question, "model": settings.model}) as root:
        runtime.root_observation = root
        state = invoke_graph(state, runtime)
    assert state.final_result is not None
    return state.final_result
