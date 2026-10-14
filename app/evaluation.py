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
    from .evaluator_specs import ANSWER_CORRECTNESS_V1, CITATION_SUPPORT_V1
    from .observability import observation, update as update_observation, use_client
except ImportError:
    from evaluator_specs import ANSWER_CORRECTNESS_V1, CITATION_SUPPORT_V1
    from observability import observation, update as update_observation, use_client


def _judge(spec: Any, *, question: str, answer: str, expected: str | None, evidence: str = "",
           evaluator_id: str | None = None, langfuse_client: Any = None) -> dict[str, Any]:
    prompt = spec.prompt_template.format(question=question, reference_answer=expected or "", answer=answer,
                                        evidence=evidence, rubric=spec.rubric)
    model = os.getenv("EVALUATOR_MODEL", "qwen3:8b")
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    last_error: Exception | None = None
    started = time.perf_counter()
    for attempt in range(2):
        try:
            with use_client(langfuse_client), observation(spec.name, as_type="evaluator", model=model,
                             input=prompt, metadata={"evaluator_id": evaluator_id, "evaluator_version": spec.version}) as obs:
                response = requests.post(f"{url}/api/chat", json={"model": model,
                    "messages":[{"role":"user","content":prompt}],"stream":False,"format":"json",
                    "options":{"temperature":0}}, timeout=(10, 300))
                response.raise_for_status()
                raw = response.json().get("message", {}).get("content", "")
                update_observation(obs, output=raw)
                data = json.loads(raw)
                score = data.get("score")
                explanation = str(data.get("explanation", "")).strip()
                if score is None and spec is CITATION_SUPPORT_V1 and re.search(r"\b(insufficient|cannot determine|no factual claims|I don't know)\b", answer, re.I):
                    return {"score": None, "explanation": explanation or "not applicable: explicit abstention",
                            "latency_seconds": round(time.perf_counter() - started, 4)}
                if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or not spec.minimum <= score <= spec.maximum or not explanation:
                    raise ValueError("judge JSON must have a finite in-range numeric score and explanation")
                return {"score": float(score), "explanation": explanation,
                        "latency_seconds": round(time.perf_counter() - started, 4)}
        except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
    raise RuntimeError(f"{spec.name} evaluation failed after one retry: {last_error}")


def correctness(*, input: Any, output: Any, expected_output: Any = None, **kwargs: Any) -> Any:
    if isinstance(output, dict) and output.get("error"):
        return []
    answer = output.get("answer", "") if isinstance(output, dict) else str(output)
    question = input.get("question", "") if isinstance(input, dict) else str(input)
    expected = expected_output.get("answer", "") if isinstance(expected_output, dict) else expected_output
    try:
        evaluator_id = kwargs.get("evaluator_id")
        result = _judge(ANSWER_CORRECTNESS_V1, question=question, answer=answer, expected=str(expected or ""),
                        evaluator_id=evaluator_id, langfuse_client=kwargs.get("langfuse_client"))
    except Exception as exc:
        return {"name": "answer_correctness_v1_error", "value": "error", "comment": str(exc), "data_type": "CATEGORICAL",
                "metadata": {"evaluator_id": kwargs.get("evaluator_id")}}
    return {"name": ANSWER_CORRECTNESS_V1.name, "value": result["score"], "comment": result["explanation"],
            "metadata": {"evaluator_model": os.getenv("EVALUATOR_MODEL", "qwen3:8b"), "evaluator_version": 1,
                         "evaluator_latency_seconds": result["latency_seconds"], "evaluator_id": kwargs.get("evaluator_id")}}


def citation_support(*, input: Any, output: Any, expected_output: Any = None, **kwargs: Any) -> Any:
    if isinstance(output, dict) and output.get("error"):
        return []
    answer = output.get("answer", "") if isinstance(output, dict) else str(output)
    evidence = output.get("evidence", "") if isinstance(output, dict) else ""
    question = input.get("question", "") if isinstance(input, dict) else str(input)
    try:
        evaluator_id = kwargs.get("evaluator_id")
        result = _judge(CITATION_SUPPORT_V1, question=question, answer=answer, evidence=evidence,
                        evaluator_id=evaluator_id, langfuse_client=kwargs.get("langfuse_client"))
    except Exception as exc:
        return {"name": "citation_support_v1_error", "value": "error", "comment": str(exc), "data_type": "CATEGORICAL",
                "metadata": {"evaluator_id": kwargs.get("evaluator_id")}}
    if result["score"] is None:
        return {"name": "citation_support_v1_status", "value": "not_applicable", "comment": result["explanation"],
                "data_type": "CATEGORICAL", "metadata": {"reason": result["explanation"], "evaluator_id": kwargs.get("evaluator_id")}}
    return {"name": CITATION_SUPPORT_V1.name, "value": result["score"], "comment": result["explanation"],
            "metadata": {"evaluator_model": os.getenv("EVALUATOR_MODEL", "qwen3:8b"), "evaluator_version": 1,
                         "evaluator_latency_seconds": result["latency_seconds"], "evaluator_id": kwargs.get("evaluator_id")}}
