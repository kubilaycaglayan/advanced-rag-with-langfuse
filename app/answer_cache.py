"""Persistent, approval-gated exact-answer cache backed by Redis."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from collections import defaultdict
from functools import lru_cache
from typing import Any
from urllib.parse import quote

try:
    from .identity import canonical_json
except ImportError:
    from identity import canonical_json

logger = logging.getLogger(__name__)
CACHE_FORMAT = 1
LAYERS = {"answer"}
PENDING_DAYS = 30
PENDING_SECONDS = PENDING_DAYS * 24 * 60 * 60
ANSWER_FIELDS = {
    "question", "answer", "citations", "reranked", "candidates", "baseline", "evidence",
    "generated_queries", "generation_model", "agent_model", "agent_provider", "engine", "mode",
    "pipeline_id", "pipeline_version", "pipeline_derived", "pipeline_status", "corpus_id",
    "corpus_checksum", "profile_id", "profile_identity", "prompt_identity", "prompts",
}
KEY_ROOT = "answer-cache:v1"


@lru_cache(maxsize=1)
def _redis_client():
    import redis
    return redis.Redis.from_url(
        os.getenv("ANSWER_CACHE_REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.25,
        health_check_interval=30)


def normalize_layers(layers: list[str] | None) -> tuple[str, ...]:
    if layers is None:
        return ("answer",)
    if not isinstance(layers, list) or any(not isinstance(layer, str) for layer in layers):
        raise ValueError("cache_layers must be an array of strings")
    unknown = sorted(set(layers) - LAYERS)
    if unknown:
        raise ValueError(f"unsupported cache layer(s): {', '.join(unknown)}")
    return tuple(dict.fromkeys(layers))


def identity(*, project_id: str, corpus_id: str, pipeline_version: str,
             pipeline_fingerprint: str, pipeline_id: str, corpus_checksum: str,
             profile_id: str, profile_identity: str, prompt_identity: str,
             collection: str, question: str, config: dict[str, Any],
             agent_settings: dict[str, Any] | None) -> dict[str, Any]:
    """Build the complete namespace and exact-input identity for one answer."""
    dimensions = {
        "cache_format": CACHE_FORMAT,
        "project_id": project_id,
        "corpus_id": corpus_id,
        "pipeline_version": pipeline_version,
        "pipeline_fingerprint": pipeline_fingerprint,
        "pipeline_id": pipeline_id,
        "corpus_checksum": corpus_checksum,
        "profile_id": profile_id,
        "profile_identity": profile_identity,
        "prompt_identity": prompt_identity,
        "collection": collection,
        "config": config,
        "agent_settings": agent_settings,
        "question": question,
    }
    return {**dimensions, "cache_key": hashlib.sha256(canonical_json(dimensions).encode("utf-8")).hexdigest()}


def _scope_prefix(scope: dict[str, Any]) -> str:
    project = quote(str(scope["project_id"]), safe="")
    corpus = quote(str(scope["corpus_id"]), safe="")
    pipeline = quote(str(scope["pipeline_version"]), safe="")
    return f"{KEY_ROOT}:project/{project}:corpus/{corpus}:pipeline/{pipeline}"


def _answer_key(scope: dict[str, Any]) -> str:
    return f"{_scope_prefix(scope)}:answer/{scope['cache_key']}"


def _answer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key in ANSWER_FIELDS}


def lookup(scope: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str | None]:
    try:
        encoded = _redis_client().get(_answer_key(scope))
        if encoded is None:
            return None, "miss", None
        record = json.loads(encoded)
        payload = record.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str):
            _redis_client().delete(_answer_key(scope))
            return None, "miss", None
        return payload, "hit", record.get("source_trace_id")
    except Exception as exc:
        logger.warning("Answer cache lookup failed: %s", exc)
        return None, "unavailable", None


def stage_candidate(scope: dict[str, Any], payload: dict[str, Any], *,
                    trace_id: str | None, owner_id: str | None) -> bool:
    if not trace_id or not owner_id or not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        return False
    candidate = {"scope": scope, "payload": _answer_payload(payload), "owner_id": owner_id}
    try:
        _redis_client().set(f"{KEY_ROOT}:pending/{trace_id}", canonical_json(candidate), ex=PENDING_SECONDS)
        return True
    except Exception as exc:
        logger.warning("Answer cache candidate write failed: %s", exc)
        return False


def mark_served(*, trace_id: str | None, scope: dict[str, Any], owner_id: str | None,
                source_trace_id: str | None) -> bool:
    if not trace_id or not owner_id:
        return False
    try:
        served = {"scope": scope, "owner_id": owner_id, "source_trace_id": source_trace_id}
        _redis_client().set(f"{KEY_ROOT}:served/{trace_id}", canonical_json(served), ex=PENDING_SECONDS)
        return True
    except Exception as exc:
        logger.warning("Answer cache served-answer write failed: %s", exc)
        return False


def store_approved(scope: dict[str, Any], payload: dict[str, Any], *,
                   trace_id: str | None, approval_source: str,
                   correctness_score: float | None = None) -> bool:
    if approval_source == "correctness":
        if correctness_score is None or correctness_score <= 0.95:
            return False
    elif approval_source != "thumbs_up":
        raise ValueError("approval_source must be correctness or thumbs_up")
    if not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        return False
    value = {"scope": scope, "payload": _answer_payload(payload), "source_trace_id": trace_id,
             "approval_source": approval_source, "correctness_score": correctness_score}
    try:
        _redis_client().set(_answer_key(scope), canonical_json(value))
        return True
    except Exception as exc:
        logger.warning("Approved answer cache write failed: %s", exc)
        return False


def record_feedback(*, trace_id: str, owner_id: str, helpful: bool) -> str:
    """Promote a held answer on thumbs-up, or invalidate a served answer on thumbs-down."""
    client = _redis_client()
    pending_key, served_key = f"{KEY_ROOT}:pending/{trace_id}", f"{KEY_ROOT}:served/{trace_id}"
    pending_raw, served_raw = client.get(pending_key), client.get(served_key)
    pending = json.loads(pending_raw) if pending_raw else None
    served = json.loads(served_raw) if served_raw else None
    record = pending or served
    if record is None:
        return "not_found"
    if record.get("owner_id") != owner_id:
        raise PermissionError("answer does not belong to this browser session")
    if helpful and pending:
        scope = pending["scope"]
        if not store_approved(scope, pending["payload"], trace_id=trace_id, approval_source="thumbs_up"):
            raise RuntimeError("approved answer could not be written to cache")
        client.delete(pending_key)
        client.set(served_key, canonical_json({"scope": scope, "owner_id": owner_id,
                    "source_trace_id": trace_id}), ex=PENDING_SECONDS)
        return "promoted"
    if not helpful and served:
        key = _answer_key(served["scope"])
        current = client.get(key)
        source_trace_id = json.loads(current).get("source_trace_id") if current else None
        if current and source_trace_id == served.get("source_trace_id"):
            client.delete(key)
            client.delete(served_key)
            return "invalidated"
        client.delete(served_key)
        return "not_approved"
    return "not_approved"


def _matches(scope: dict[str, Any], project_id: str, corpus_id: str,
             pipeline_version: str | None, question: str | None) -> bool:
    return (scope.get("project_id") == project_id and scope.get("corpus_id") == corpus_id
            and (pipeline_version is None or scope.get("pipeline_version") == pipeline_version)
            and (question is None or scope.get("question") == question))


def _scan(match: str) -> list[str]:
    return list(_redis_client().scan_iter(match=match, count=200))


def clear(*, project_id: str | None, selected_corpus_id: str | None,
          pipeline_version: str | None, question: str | None, all_entries: bool = False) -> int:
    client = _redis_client()
    if all_entries:
        keys = _scan(f"{KEY_ROOT}:*")
        approved_count = sum(":answer/" in key for key in keys)
        if keys:
            client.delete(*keys)
        return approved_count
    if not project_id or not selected_corpus_id:
        raise ValueError("scoped cache clearing requires --project-id and --corpus-id; use --all for a whole-cache clear")
    prefix = (f"{KEY_ROOT}:project/{quote(project_id, safe='')}:"
              f"corpus/{quote(selected_corpus_id, safe='')}:pipeline/")
    answer_pattern = (f"{prefix}{quote(pipeline_version, safe='')}:answer/*"
                      if pipeline_version else f"{prefix}*:answer/*")
    keys_to_delete: set[str] = set()
    for key in _scan(answer_pattern):
        try:
            record = json.loads(client.get(key) or "{}")
            scope = record.get("scope") or {}
            if question is None or scope.get("question") == question:
                keys_to_delete.add(key)
        except (TypeError, ValueError):
            keys_to_delete.add(key)
    for kind in ("pending", "served"):
        for key in _scan(f"{KEY_ROOT}:{kind}/*"):
            try:
                record = json.loads(client.get(key) or "{}")
                scope = record.get("scope") or {}
                if _matches(scope, project_id, selected_corpus_id, pipeline_version, question):
                    keys_to_delete.add(key)
            except (TypeError, ValueError):
                continue
    answer_count = sum(":answer/" in key for key in keys_to_delete)
    if keys_to_delete:
        client.delete(*keys_to_delete)
    return answer_count


def stats() -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: {"entries": 0, "payload_bytes": 0})
    client = _redis_client()
    for key in _scan(f"{KEY_ROOT}:project/*:corpus/*:pipeline/*:answer/*"):
        try:
            record = json.loads(client.get(key) or "{}")
            scope = record.get("scope") or {}
            group = grouped[(scope["project_id"], scope["corpus_id"], scope["pipeline_version"])]
            group["entries"] += 1
            group["payload_bytes"] += len(canonical_json(record).encode("utf-8"))
        except (TypeError, ValueError, KeyError):
            continue
    return [{"project_id": project, "corpus_id": corpus, "pipeline_version": pipeline, **counts}
            for (project, corpus, pipeline), counts in sorted(grouped.items())]


def cli() -> int:
    parser = argparse.ArgumentParser(description="Inspect or clear approved exact-answer cache entries")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stats", help="show approved entries grouped by project, corpus and pipeline")
    remove = commands.add_parser("clear", help="clear a scoped cache or explicitly clear all entries")
    remove.add_argument("--project-id")
    remove.add_argument("--corpus-id")
    remove.add_argument("--pipeline-version")
    remove.add_argument("--question")
    remove.add_argument("--all", action="store_true", dest="all_entries")
    args = parser.parse_args()
    if args.command == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"deleted": clear(project_id=args.project_id,
                selected_corpus_id=args.corpus_id, pipeline_version=args.pipeline_version,
                question=args.question, all_entries=args.all_entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
