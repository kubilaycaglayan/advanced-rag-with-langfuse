"""Local Ollama judges with strict JSON/range validation."""
from __future__ import annotations

import json
import math
import os
import re
import time
from typing import Any

import requests

try:
    from .evaluator_specs import ANSWER_CORRECTNESS_V1, ANSWER_CORRECTNESS_V2, CITATION_SUPPORT_V1
    from .observability import observation, update as update_observation, use_client
except ImportError:
    from evaluator_specs import ANSWER_CORRECTNESS_V1, ANSWER_CORRECTNESS_V2, CITATION_SUPPORT_V1
    from observability import observation, update as update_observation, use_client


_ABSTENTION_PATTERN = re.compile(
    r"\b(insufficient|cannot determine|no factual claims|I don't know|could not find|"
    r"not possible to answer|cannot be answered|does not indicate|do not indicate|"
    r"none of (?:the )?(?:provided )?(?:evidence|passages)|no (?:relevant )?evidence|"
    r"not mentioned in (?:the )?(?:evidence|passages)|does not contain (?:any )?information|"
    r"not found in (?:the )?(?:sources|evidence|passages))\b",
    re.I,
)


def is_explicit_abstention(answer: str) -> bool:
    return bool(_ABSTENTION_PATTERN.search(answer or ""))


FACT_POINTS = {"present": 1.0, "partial": 0.5, "missing": 0.0}
# Items without listed facts are judged on the reference's core answer alone.
FALLBACK_FACTS = (["The core answer that the reference answer gives to the question"], [])


def answer_facts(expected_output: Any) -> tuple[list[str], list[str]]:
    if isinstance(expected_output, dict) and expected_output.get("required_facts"):
        return [str(fact) for fact in expected_output["required_facts"]], [str(fact) for fact in expected_output.get("supporting_details") or []]
    return FALLBACK_FACTS


def _fact_ids(facts: tuple[list[str], list[str]]) -> list[str]:
    return [f"R{n}" for n in range(1, len(facts[0]) + 1)] + [f"D{n}" for n in range(1, len(facts[1]) + 1)]


def _fact_schema(facts: tuple[list[str], list[str]]) -> dict[str, Any]:
    # A JSON schema makes Ollama return a verdict for every fact ID; free-form JSON
    # dropped or relabelled verdicts in trials.
    fact = {"type": "object", "properties": {"quote": {"type": "string"}, "verdict": {"type": "string", "enum": list(FACT_POINTS)}},
            "required": ["quote", "verdict"]}
    ids = _fact_ids(facts)
    return {"type": "object", "properties": {**{fact_id: fact for fact_id in ids}, "explanation": {"type": "string"}},
            "required": ids + ["explanation"]}


def fact_score(verdicts: dict[str, Any], n_required: int, n_details: int) -> float:
    """Required facts carry 90% of the score and supporting details 10% (all of it without details)."""
    points = lambda fact_id: FACT_POINTS[str(verdicts[fact_id]["verdict"]).lower()]
    score = sum(points(f"R{n}") for n in range(1, n_required + 1)) / n_required
    if n_details:
        score = 0.9 * score + 0.1 * sum(points(f"D{n}") for n in range(1, n_details + 1)) / n_details
    return round(score, 4)


def _judge(spec: Any, *, question: str, answer: str, expected: str | None = None, evidence: str = "",
           evaluator_id: str | None = None, langfuse_client: Any = None, managed_prompt: Any = None,
           evaluator_version: int | None = None, managed_evaluator_id: str | None = None,
           facts: tuple[list[str], list[str]] | None = None) -> dict[str, Any]:
    values = {"question": question, "reference_answer": expected or "", "answer": answer,
              "evidence": evidence, "rubric": spec.rubric}
    if facts is not None:
        values["required_facts"] = "\n".join(f"R{n}. {fact}" for n, fact in enumerate(facts[0], 1))
        values["supporting_details"] = "\n".join(f"D{n}. {fact}" for n, fact in enumerate(facts[1], 1)) or "(none)"
    prompt = managed_prompt.compile(**values) if managed_prompt is not None else spec.prompt_template.format(**values)
    model = getattr(managed_prompt, "model", None) or os.getenv("EVALUATOR_MODEL", "qwen3:8b")
    # Keep the judge connection independently configurable so generation and
    # evaluation failures can be isolated and the evaluator can use its own host.
    url = (os.getenv("EVALUATOR_OLLAMA_URL") or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
    last_error: Exception | None = None
    started = time.perf_counter()
    for attempt in range(2):
        try:
            with use_client(langfuse_client), observation(spec.name, as_type="evaluator", model=model,
                             input=prompt, metadata={"evaluator_id": evaluator_id,
                                "evaluator_version": evaluator_version or spec.version,
                                "managed_evaluator_id": managed_evaluator_id}) as obs:
                response = requests.post(f"{url}/api/chat", json={"model": model,
                    "messages": prompt if isinstance(prompt, list) else [{"role":"user","content":prompt}],
                    "think": False, "stream":False,"format": _fact_schema(facts) if facts is not None else "json",
                    "options":{"temperature":0}}, timeout=(10, 300))
                response.raise_for_status()
                raw = response.json().get("message", {}).get("content", "")
                update_observation(obs, output=raw)
                data = json.loads(raw)
                if facts is not None:
                    explanation = str(data.get("explanation", "")).strip()
                    if not explanation:
                        raise ValueError("judge JSON must have an explanation")
                    verdicts = {fact_id: data[fact_id] for fact_id in _fact_ids(facts)}
                    return {"score": fact_score(verdicts, len(facts[0]), len(facts[1])), "explanation": explanation,
                            "verdicts": verdicts, "latency_seconds": round(time.perf_counter() - started, 4)}
                score = data.get("score")
                explanation = str(data.get("explanation", data.get("reasoning", ""))).strip()
                abstention_explanation = re.search(r"\b(not applicable|no factual claims|explicitly abstains?)\b", explanation, re.I)
                if score is None and spec is CITATION_SUPPORT_V1 and is_explicit_abstention(answer) and abstention_explanation:
                    return {"score": None, "explanation": explanation or "not applicable: explicit abstention",
                            "latency_seconds": round(time.perf_counter() - started, 4)}
                if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or not spec.minimum <= score <= spec.maximum or not explanation:
                    raise ValueError("judge JSON must have a finite in-range numeric score and explanation")
                return {"score": float(score), "explanation": explanation,
                        "latency_seconds": round(time.perf_counter() - started, 4)}
        except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
    raise RuntimeError(f"{spec.name} evaluation failed after one retry: {last_error}")


def correctness(*, input: Any, output: Any, expected_output: Any = None, spec: Any = ANSWER_CORRECTNESS_V1, **kwargs: Any) -> Any:
    if isinstance(output, dict) and output.get("error"):
        return []
    answer = output.get("answer", "") if isinstance(output, dict) else str(output)
    question = input.get("question", "") if isinstance(input, dict) else str(input)
    expected = expected_output.get("answer", "") if isinstance(expected_output, dict) else expected_output
    try:
        evaluator_id = kwargs.get("evaluator_id")
        result = _judge(spec, question=question, answer=answer, expected=str(expected or ""),
                        evaluator_id=evaluator_id, langfuse_client=kwargs.get("langfuse_client"),
                        managed_prompt=kwargs.get("managed_prompt"), evaluator_version=kwargs.get("evaluator_version"),
                        managed_evaluator_id=kwargs.get("managed_evaluator_id"),
                        facts=answer_facts(expected_output) if spec is ANSWER_CORRECTNESS_V2 else None)
    except Exception as exc:
        return {"name": f"{spec.name}_error", "value": "error", "comment": str(exc), "data_type": "CATEGORICAL",
                "metadata": {"evaluator_id": kwargs.get("evaluator_id"), "managed_evaluator_id": kwargs.get("managed_evaluator_id"),
                             "managed_evaluator_version": kwargs.get("evaluator_version")}}
    metadata = {"evaluator_model": getattr(kwargs.get("managed_prompt"), "model", None) or os.getenv("EVALUATOR_MODEL", "qwen3:8b"), "evaluator_version": kwargs.get("evaluator_version", 1),
                "managed_evaluator_id": kwargs.get("managed_evaluator_id"),
                "evaluator_latency_seconds": result["latency_seconds"], "evaluator_id": kwargs.get("evaluator_id")}
    if "verdicts" in result:
        metadata["fact_verdicts"] = {fact_id: verdict["verdict"] for fact_id, verdict in result["verdicts"].items()}
    return {"name": spec.name, "value": result["score"], "comment": result["explanation"], "metadata": metadata}


def citation_support(*, input: Any, output: Any, expected_output: Any = None, **kwargs: Any) -> Any:
    if isinstance(output, dict) and output.get("error"):
        return []
    answer = output.get("answer", "") if isinstance(output, dict) else str(output)
    evidence = output.get("evidence", "") if isinstance(output, dict) else ""
    question = input.get("question", "") if isinstance(input, dict) else str(input)
    cited_labels = set(re.findall(r"\[(E\d+)\]", answer))
    evidence_labels = set(re.findall(r"\[(E\d+)\]", evidence))
    invalid_labels = sorted(cited_labels - evidence_labels)
    if invalid_labels:
        # The rubric forbids nonexistent evidence labels from supporting a
        # factual claim. Enforce that invariant locally; a probabilistic judge
        # has returned a perfect score for an invalid label in live runs.
        comment = f"Citation label(s) {', '.join(f'[{label}]' for label in invalid_labels)} are absent from the supplied evidence and cannot support claims."
        metadata = {"evaluator_id": kwargs.get("evaluator_id"),
                    "evaluator_version": kwargs.get("evaluator_version", 1),
                    "managed_evaluator_id": kwargs.get("managed_evaluator_id"),
                    "managed_evaluator_version": kwargs.get("evaluator_version", 1),
                    "validation": "invalid_citation_label", "invalid_labels": invalid_labels}
        with use_client(kwargs.get("langfuse_client")), observation(CITATION_SUPPORT_V1.name,
                 as_type="evaluator", model="deterministic-citation-validator",
                 input={"question": question, "answer": answer, "evidence": evidence}, metadata=metadata) as obs:
            update_observation(obs, output={"score": 0.0, "explanation": comment})
        return {"name": CITATION_SUPPORT_V1.name, "value": 0.0, "comment": comment,
                "metadata": {"evaluator_model": "deterministic-citation-validator",
                             "evaluator_version": kwargs.get("evaluator_version", 1),
                             "managed_evaluator_id": kwargs.get("managed_evaluator_id"),
                             "evaluator_latency_seconds": 0.0, "evaluator_id": kwargs.get("evaluator_id"),
                             "validation": "invalid_citation_label"}}
    try:
        evaluator_id = kwargs.get("evaluator_id")
        result = _judge(CITATION_SUPPORT_V1, question=question, answer=answer, evidence=evidence,
                        evaluator_id=evaluator_id, langfuse_client=kwargs.get("langfuse_client"),
                        managed_prompt=kwargs.get("managed_prompt"), evaluator_version=kwargs.get("evaluator_version"),
                        managed_evaluator_id=kwargs.get("managed_evaluator_id"))
    except Exception as exc:
        return {"name": "citation_support_v1_error", "value": "error", "comment": str(exc), "data_type": "CATEGORICAL",
                "metadata": {"evaluator_id": kwargs.get("evaluator_id"), "managed_evaluator_id": kwargs.get("managed_evaluator_id"),
                             "managed_evaluator_version": kwargs.get("evaluator_version")}}
    if result["score"] is None:
        return {"name": "citation_support_v1_status", "value": "not_applicable", "comment": result["explanation"],
                "data_type": "CATEGORICAL", "metadata": {"reason": result["explanation"], "evaluator_id": kwargs.get("evaluator_id"),
                    "managed_evaluator_id": kwargs.get("managed_evaluator_id"), "managed_evaluator_version": kwargs.get("evaluator_version")}}
    return {"name": CITATION_SUPPORT_V1.name, "value": result["score"], "comment": result["explanation"],
            "metadata": {"evaluator_model": getattr(kwargs.get("managed_prompt"), "model", None) or os.getenv("EVALUATOR_MODEL", "qwen3:8b"), "evaluator_version": kwargs.get("evaluator_version", 1),
                         "managed_evaluator_id": kwargs.get("managed_evaluator_id"),
                         "evaluator_latency_seconds": result["latency_seconds"], "evaluator_id": kwargs.get("evaluator_id")}}
