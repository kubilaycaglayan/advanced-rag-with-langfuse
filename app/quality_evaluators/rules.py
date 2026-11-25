"""Repository definitions for native Langfuse quality-evaluation routing."""
import argparse
import json

import requests

from app.quality_evaluators.client import project_api, list_resources
from app.quality_evaluators.config import configuration

OBSERVATION_NAME = configuration().observation_name
QUESTION_TYPES = ("normal", "single_evidence", "broad")


def observation_metadata(item, **record):
    """Normalize qrels types for rule filtering; fail closed on unknown types."""
    question_type = item.get("question_type") or (
        "single_evidence" if item.get("single_evidence") else "normal")
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"Unknown question type: {question_type!r}")
    if bool(item.get("single_evidence")) != (question_type == "single_evidence"):
        raise ValueError("Conflicting question_type and single_evidence labels")
    config = configuration()
    ready = item.get("retrieval_metrics_ready", True) and item.get("question_type_status") != "awaiting_user"
    return {**record, "corpus": config.corpus, "question_type": question_type,
            "pipeline_version": config.pipeline, **config.agent_settings,
            "retrieval_evaluation": "enabled" if ready and question_type != "broad" else "skip"}


def definitions(evaluator_ids):
    config = configuration()
    common = [
        {"type": "stringOptions", "column": "name", "operator": "any of",
         "value": [config.observation_name]},
        {"type": "stringObject", "column": "metadata", "key": "pipeline_version",
         "operator": "=", "value": config.pipeline},
    ]
    common.extend({"type": "stringObject", "column": "metadata", "key": key,
                   "operator": "=", "value": value} for key, value in config.agent_settings.items())
    return [
        {"name": name, "enabled": True, "sampling": 1,
         "filter": [*common, route_filter],
         "evaluatorAssignments": [{"evaluatorId": evaluator_ids[e]} for e in evaluators]}
        for name, route_filter, evaluators in [
            (config.evaluator_name("retrieval-rule"),
             {"type": "stringObject", "column": "metadata", "key": "retrieval_evaluation",
              "operator": "=", "value": "enabled"},
             [config.evaluator_name("retrieval")]),
            (config.evaluator_name("answer-quality-rule"),
             {"type": "stringObject", "column": "metadata", "key": "question_type",
              "operator": "is set", "value": ""},
             [config.evaluator_name("faithfulness"), config.evaluator_name("relevancy")]),
        ]
    ]


def reconcile(write=False):
    config = configuration()
    base, auth = project_api()
    evaluators = list_resources(base, auth, "evaluators")
    ids = {}
    for name in (config.evaluator_name("retrieval"), config.evaluator_name("faithfulness"), config.evaluator_name("relevancy")):
        matches = [e for e in evaluators if e["name"] == name]
        if len(matches) != 1 or matches[0]["status"] != "active":
            raise ValueError(f"Expected one active evaluator: {name}")
        ids[name] = matches[0]["id"]
    existing = list_resources(base, auth, "evaluation-rules")
    results = []
    for definition in definitions(ids):
        matches = [r for r in existing if r["name"] == definition["name"]]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous rule name: {definition['name']}")
        row = matches[0] if matches else None
        actual = {k: row.get(k) for k in definition} if row else None
        if actual:
            actual["evaluatorAssignments"] = [
                {"evaluatorId": e["evaluatorId"]} for e in actual["evaluatorAssignments"]]
        changed = actual != definition
        if write and changed:
            url = base + "/api/public/v2/evaluation-rules" + ("/" + row["id"] if row else "")
            response = requests.request("PATCH" if row else "POST", url,
                                        json=definition, auth=auth, timeout=30)
            if not response.ok:
                raise RuntimeError(f"Rule update failed ({response.status_code}): {response.text}")
            response.raise_for_status()
            row = response.json()
        results.append({"id": (row or {}).get("id"), "changed": changed, **definition})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    print(json.dumps(reconcile(parser.parse_args().write), indent=2))
