"""agent / tools / submission responsibilities."""
from __future__ import annotations

from app.agent.state import AgentState
from app.agent.tools.coverage import _coverage_gap
from typing import Any
import re


def _tool_submit_answer(state: AgentState, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    answer = str(args.get("answer") or "").strip()
    if not answer:
        return {"error": "answer is required"}, False
    raw_ids = args.get("passage_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = re.split(r"[\s,]+", raw_ids)
    ids: list[str] = []
    unknown: list[str] = []
    for wanted in raw_ids:
        text = str(wanted).strip().strip("[]")
        if not text:
            continue
        short = text[:8].casefold()
        if short in state.evidence:
            if short not in ids:
                ids.append(short)
        else:
            unknown.append(text)
    if not state.evidence and not ids:
        return {"error": "no evidence yet: search the books before answering"}, False
    minimum = 1 if state.speech_hint else state.settings.min_tool_calls
    if state.tool_calls < minimum:
        return {"error": f"investigate more before answering: at least {minimum} tool calls "
                         f"(you made {state.tool_calls}); a passage that is only on topic is not evidence"}, False
    if unknown:
        return {"error": f"unknown passage ids: {unknown}. Use the 8-character ids the tools returned."}, False
    gap = _coverage_gap(state, answer)
    if gap:
        return gap, False
    labels = {short: f"[E{position}]" for position, short in enumerate(ids, 1)}
    cited = re.findall(r"\[([0-9a-fA-F]{8})\]", answer)

    def replace(match: re.Match[str]) -> str:
        short = match.group(1).casefold()
        return labels.get(short, match.group(0))

    rewritten = re.sub(r"\[([0-9a-fA-F]{8})\]", replace, answer)
    return {"answer": rewritten, "raw_answer": answer, "passage_ids": ids,
            "cited_ids": list(dict.fromkeys(item.casefold() for item in cited)),
            "uncited": bool(ids) and not any(item.casefold() in ids for item in cited)}, True

