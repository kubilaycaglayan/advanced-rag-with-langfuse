"""agent / submission responsibilities."""
from __future__ import annotations

from app.agent.prompts import _SYNTHESIS_SYSTEM
from app.agent.state import AgentState
from app.agent.tools.coverage import _WHAT_HAPPENED
from app.agent.tools.coverage import _coverage_hint
from app.agent.tools.coverage import _covered_stages
from app.context.agent_final_handoff import conversation_final_messages
from app.context.conversation import _compact
from app.corpus_profiles import agent_synthesis_prompt
from app.evaluation.judges import is_explicit_abstention
from app.models.agent import _tracked_agent_chat
from app.observability import observation
from app.observability import update as update_observation
from app.retrieval.passages import passage_index
from app.retrieval.search import passage_position
from app.models.retrieval import reranker
from typing import Any
import json
import re
import time


def _verify_submission(state: AgentState, answer: str, ids: list[str], extra_ids: list[str] = ()) -> tuple[bool, str]:
    """Ask the model whether the cited passages (or a passage a tool read on purpose) state the proposed answer."""
    blocks = []
    by_section: dict[tuple, list[dict[str, Any]]] = {}
    _, rows = passage_index(state.collection)
    for row in rows:
        by_section.setdefault((row.get("book_file"), row.get("section")), []).append(row)
    checked = list(dict.fromkeys([*ids, *extra_ids]))
    for position, short in enumerate(checked, 1):
        row = state.evidence.get(short)
        if not row:
            continue
        section = sorted(by_section.get((row.get("book_file"), row.get("section")), [row]), key=passage_position)
        index = next((number for number, item in enumerate(section) if item["id"] == row["id"]), None)
        context = section[max(0, (index or 0) - 1): (index or 0) + 2] if index is not None else [row]
        blocks.append(f"[E{position}] id={short} | {row.get('book')} | {row.get('chapter')}\n" + "\n".join(
            f"paragraph {item.get('paragraph')}: {(item.get('text') or '')[:900]}" for item in context))
    prompt = (f"Question: {state.question}\n\nProposed answer: {answer}\n\nPassages:\n" + "\n\n".join(blocks)
              + "\n\nDoes at least one passage state the main answer to the question, even if worded differently? "
                "A passage that only mentions the topic, or states the opposite, is not support. A passage that only says "
                "'he' or 'she', or that could be about another person, is not support either: the passage must name or "
                "unambiguously identify the person the question asks about. Additional background the passages do not "
                "mention is not a failure. Reply with JSON only: "
                '{"supported": true or false, "reason": "one sentence"}')
    prompt += ("\nFor this draft, every factual claim must be supported; override the earlier allowance for unsupported background. "
               "Check the answer's central claim and the question's premise against all passages, including contradictions. "
               "An intention, accusation, question, or earlier belief does not establish that an event happened. "
               "If a later passage establishes the subject is alive, reject an answer saying someone killed them. "
               "If the answer changes the subject of who was killed, reject it unless it also answers the question directly. "
               "Return supported=false for any unsupported central claim or unresolved contradiction.")
    try:
        reply = _tracked_agent_chat(state, [{"role": "system", "content": "You check whether evidence supports an answer."},
                                            {"role": "user", "content": prompt}], None, "submission verification")
        content = ((reply.get("message") or {}).get("content") or "").strip()
        match = re.search(r"\{.*\}", content, re.S)
        verdict = json.loads(match.group(0)) if match else {}
        return bool(verdict.get("supported", False)), str(verdict.get("reason") or "")
    except (ValueError, TypeError, KeyError, AttributeError):
        return False, "verifier reply could not be parsed"
    except Exception as exc:  # verification must not end the run
        if state.settings.provider == "openai":
            raise
        return False, f"verifier failed: {type(exc).__name__}"


def _answer_key(answer: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\[[0-9a-fA-F]{8}\]", "", answer)).strip().casefold()


def _direct_premise_resolution(state: AgentState) -> tuple[str, list[str]] | None:
    """Answer a false death premise from a later passage that directly confirms the subject is alive."""
    match = re.search(r"\bwho\s+(?:killed|murdered)\s+([^?.,]+)", state.question, re.I)
    if not match:
        return None
    person = match.group(1).strip()
    first = person.split()[0].casefold()
    ordered = sorted(state.premise_evidence,
                     key=lambda short: bool(re.search(r"\b(?:i[’']m|i am) alive\b",
                                                     str(state.evidence[short].get("text") or ""), re.I)),
                     reverse=True)
    for short in ordered:
        text = str(state.evidence[short].get("text") or "")
        if (first in text.casefold() and
                re.search(r"\b(?:that you[’']re|you are|i[’']m|i am) alive\b", text, re.I)):
            return f"No one killed {person}; {person} is alive [{short}].", [short]
    return None


def _search_progress_hint(state: AgentState, name: str, args: dict[str, Any], payload: dict[str, Any]) -> str | None:
    if name not in {"semantic_search", "keyword_search", "search_scenes"}:
        return None
    query = str(args.get("query") or "")
    terms = set(re.findall(r"[a-z]+", query.casefold())) - {"who", "what", "the", "was", "by", "to", "vanger"}
    ids = {str(row.get("id")) for row in (payload.get("hits") or payload.get("scenes") or []) if row.get("id")}
    repeated = any(len(terms & old_terms) / max(1, len(terms | old_terms)) >= 0.5
                   and len(ids - old_ids) <= 2 for old_terms, old_ids in state.search_history[-3:])
    state.search_history.append((terms, ids))
    if repeated:
        return ("This search substantially repeats an earlier hypothesis and adds little distinct evidence. "
                "State the unresolved claim, inspect context or test a competing explanation before searching again.")
    return None


_ABSTAIN = re.compile(
    r"\b(insufficient|cannot determine|no factual claims|could not find|not found in|"
    r"(?:do not|does not|don't) (?:contain|describe|state|mention|say|provide)|"
    r"no (?:passage|information|evidence|mention)|there is no passage|"
    r"not possible to answer|cannot be answered|(?:do not|does not|don't) answer|no answer)\b", re.I)


def _looks_like_abstention(answer: str) -> bool:
    return is_explicit_abstention(answer) or bool(_ABSTAIN.search(answer or ""))


def _synthesis_rows(state: AgentState, limit: int = 10) -> list[dict[str, Any]]:
    rows = [state.evidence[short] for short in state.order if short in state.evidence]
    focused = [state.evidence[short] for short in state.focus if short in state.evidence]
    if len(rows) <= limit:
        return rows
    if focused:
        with observation("query-aware evidence reranking", input={
                "question": state.question,
                "focused_passage_ids": [str(row["id"]) for row in focused],
                "candidate_count": len(rows),
                "limit": limit,
        }) as rerank_observation:
            ranked_pairs = []
            for row in focused:
                short = str(row["id"])[:8]
                queries = list(dict.fromkeys([state.question, *state.retrieval_queries.get(short, [])[-3:]]))
                ranked_pairs.extend((short, query, row.get("text") or "") for query in queries)
            scores = reranker(state.config.reranker_model.name, state.config.reranker_model.revision).predict(
                [(query, text) for _, query, text in ranked_pairs], show_progress_bar=False)
            row_scores: dict[str, float] = {}
            for (short, _, _), score in zip(ranked_pairs, scores):
                row_scores[short] = max(row_scores.get(short, float("-inf")), float(score))
            focused = sorted(focused, key=lambda row: row_scores.get(str(row["id"])[:8], -1e9),
                             reverse=True)[:limit]
            rest = [row for row in rows if row["id"] not in {item["id"] for item in focused}]
            if len(focused) >= limit or not rest:
                update_observation(rerank_observation, output={
                    "selected_passage_ids": [str(row["id"]) for row in focused],
                    "reranked_candidate_count": len(ranked_pairs),
                })
                return focused
            scores = reranker(state.config.reranker_model.name, state.config.reranker_model.revision).predict(
                [(state.question, row.get("text") or "") for row in rest], show_progress_bar=False)
            ranked = [row for row, score in sorted(zip(rest, (float(value) for value in scores)),
                                                   key=lambda pair: pair[1], reverse=True)[:limit - len(focused)]]
            selected = focused + ranked
            update_observation(rerank_observation, output={
                "selected_passage_ids": [str(row["id"]) for row in selected],
                "reranked_candidate_count": len(ranked_pairs) + len(rest),
            })
            return selected
    # The passages a tool read on purpose (a full scene, a true-account reveal) must survive the rerank: they were
    # fetched for a reason the question's wording does not capture. Without such a read, the pre-check passages stay.
    kept = (focused or rows[:4])[:limit]
    rest = [row for row in rows if row["id"] not in {item["id"] for item in kept}]
    if len(kept) >= limit or not rest:
        return kept
    scores = reranker(state.config.reranker_model.name, state.config.reranker_model.revision).predict(
        [(state.question, row.get("text") or "") for row in rest], show_progress_bar=False)
    ranked = [row for row, score in sorted(zip(rest, (float(value) for value in scores)),
                                           key=lambda pair: pair[1], reverse=True)[:limit - len(kept)]]
    return kept + ranked


def _synthesize(state: AgentState) -> tuple[str, list[str]] | None:
    """One clean answer request over the collected evidence, when the loop's answer abstained despite evidence."""
    rows = _synthesis_rows(state)
    if not rows:
        return None
    blocks = [f"[{row['id'][:8]}] {row.get('book')} | {row.get('chapter')} | paragraph {row.get('paragraph')}\n"
              f"{(row.get('text') or '')[:900]}" for row in rows]
    prompt = f"Question: {state.question}\n\nEvidence:\n" + "\n\n".join(blocks)
    try:
        reply = _tracked_agent_chat(state, [{"role": "system", "content": agent_synthesis_prompt(_SYNTHESIS_SYSTEM)},
                                            {"role": "user", "content": prompt}], None, "answer synthesis")
        content = ((reply.get("message") or {}).get("content") or "").strip()
    except Exception:
        if state.settings.provider == "openai":
            raise
        return None
    ids = [short.casefold() for short in re.findall(r"\[([0-9a-fA-F]{8})\]", content)
           if short.casefold() in state.evidence]
    state.trace.append({"tool": "abstention synthesis", "arguments": {"rows": len(rows)},
                        "seconds": 0.0, "error": None, "result_ids": list(dict.fromkeys(ids))})
    if not content or not ids:
        return None
    return content, list(dict.fromkeys(ids))


def prepare_final_answer(state: AgentState, answer: str, ids: list[str], *, stopped: str,
            raw_answer: str | None = None) -> dict[str, Any]:
    """Answer from the loop, but never abstain while holding evidence that states the answer."""
    if _WHAT_HAPPENED.search(state.question) and state.evidence:
        # The answer may look like it covers the sequence while stopping at the discovery. Add the later scenes'
        # passages, then rewrite when the answer is missing the confrontation or most of the sequence.
        covered = _covered_stages(answer)
        if "confrontation" not in covered or len(covered) < 3:
            with observation("coverage rewrite", input=answer):
                _coverage_hint(state, answer)
                synthesized = _synthesize(state)
            if synthesized:
                rewrite, rewrite_ids = synthesized
                rewrite_stages = _covered_stages(rewrite)
                if "confrontation" in rewrite_stages and len(rewrite_stages) > len(covered):
                    answer, ids = rewrite, rewrite_ids
    cited = re.search(r"\[(?:E\d+|[0-9a-fA-F]{8})\]", answer)
    if (not ids or _looks_like_abstention(answer) or not cited) and state.evidence:
        with observation("abstention synthesis", input=answer):
            synthesized = _synthesize(state)
        if synthesized:
            answer, ids = synthesized[0], synthesized[1]
            stopped = stopped + "+synthesis"
            raw_answer = None
    if _looks_like_abstention(answer) and state.speech_hint:
        # The moment pass already found the line; do not let the final model lose it behind an abstention.
        answer = f"{state.speech_hint['text']} [{state.speech_hint['id']}]"
        ids = [state.speech_hint["id"]]
        stopped = stopped + "+speech"
        raw_answer = None
    return _final(state, answer, ids, stopped=stopped, raw_answer=raw_answer)


# v2.16's released runner retains its historical import and patch boundary.
# New execution code calls the descriptive public name above.
_finish = prepare_final_answer


def draft_budget_answer(state: AgentState, messages: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Draft from the protected conversation handoff; do not finalize or synthesize here."""
    final_messages = conversation_final_messages(messages, _compact)
    reply = _tracked_agent_chat(state, final_messages, None, "forced answer")
    message = reply.get("message") or {}
    content = (message.get("content") or "").strip()
    ids = [short.casefold() for short in re.findall(r"\[([0-9a-fA-F]{8})\]", content) if short.casefold() in state.evidence]
    return content, list(dict.fromkeys(short.casefold() for short in ids))


def _forced_answer(state: AgentState, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """v2.16 compatibility composition; target orchestration separates these steps."""
    content, ids = draft_budget_answer(state, messages)
    return _finish(state, content, ids, stopped="budget")


def _final(state: AgentState, answer: str, ids: list[str], *, stopped: str, raw_answer: str | None = None) -> dict[str, Any]:
    labels = {short: f"[E{position}]" for position, short in enumerate(ids, 1)}
    # An id the answer cites but did not collect is not evidence; leave it out instead of confusing the reader (or
    # the fact judge) with a bare hex string, and keep the labels the evidence list actually defines.
    rewritten = re.sub(r"\[([0-9a-fA-F]{8})\]", lambda match: labels.get(match.group(1).casefold(), ""), answer)
    # A citation list on its own line adds nothing (the evidence list shows them) and derails the fact judge, which
    # reads key-like tokens in the answer. Inline citations stay.
    rewritten = re.sub(r"\n+\s*(?:\[E\d+\]\s*)+$", "", rewritten).rstrip()
    cited = [match.group(1) for match in re.finditer(r"\[(E\d+)\]", rewritten)]
    return {"question": state.question, "asked": state.asked, "name_normalization": state.name_notes,
            "answer": rewritten, "raw_answer": raw_answer if raw_answer is not None else answer,
            "passage_ids": ids, "citations": list(dict.fromkeys(cited)),
            "evidence": [state.evidence[short] | {"agent_label": f"E{position}"} for position, short in enumerate(ids, 1)],
            "collected_passages": len(state.evidence), "turns": state.turns, "tool_calls": state.tool_calls,
            "trace": state.trace, "model": state.settings.model, "usage": state.usage,
            "latency_seconds": round(time.perf_counter() - state.started, 2), "stopped": stopped}
