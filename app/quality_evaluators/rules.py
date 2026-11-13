"""Repository definitions for native Langfuse quality-evaluation routing."""
import argparse
import json

import requests

from app.prompt_assets import _api

OBSERVATION_NAME = "millennium quality measurement"
QUESTION_TYPES = ("normal", "single_evidence", "broad")


def observation_metadata(item, **record):
    """Normalize qrels types for rule filtering; fail closed on unknown types."""
    question_type = item.get("question_type") or (
        "single_evidence" if item.get("single_evidence") else "normal")
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"Unknown question type: {question_type!r}")
    if bool(item.get("single_evidence")) != (question_type == "single_evidence"):
        raise ValueError("Conflicting question_type and single_evidence labels")
    return {**record, "question_type": question_type, "pipeline_version": "v2.12",
            "retrieval_evaluation": "skip" if question_type == "broad" else "enabled"}


def definitions(evaluator_ids):
    common = [
        {"type": "stringOptions", "column": "name", "operator": "any of",
         "value": [OBSERVATION_NAME]},
        {"type": "stringObject", "column": "metadata", "key": "pipeline_version",
         "operator": "=", "value": "v2.12"},
    ]
    return [
        {"name": name, "enabled": True, "sampling": 1,
         "filter": [*common, route_filter],
         "evaluatorAssignments": [{"evaluatorId": evaluator_ids[e]} for e in evaluators]}
        for name, route_filter, evaluators in [
            ("millennium-qm-retrieval-rule",
             {"type": "stringObject", "column": "metadata", "key": "retrieval_evaluation",
              "operator": "=", "value": "enabled"},
             ["millennium-qm-retrieval"]),
            ("millennium-qm-answer-quality-rule",
             {"type": "stringObject", "column": "metadata", "key": "question_type",
              "operator": "is set", "value": ""},
             ["millennium-qm-faithfulness", "millennium-qm-relevancy"]),
        ]
    ]


def reconcile(write=False):
    base, auth = _api()
    def get(resource):
        response = requests.get(base + "/api/public/v2/" + resource,
                                params={"limit": 100}, auth=auth, timeout=20)
        response.raise_for_status()
        return response.json()["data"]

    evaluators = get("evaluators")
    ids = {}
    for name in ("millennium-qm-retrieval", "millennium-qm-faithfulness", "millennium-qm-relevancy"):
        matches = [e for e in evaluators if e["name"] == name]
        if len(matches) != 1 or matches[0]["status"] != "active":
            raise ValueError(f"Expected one active evaluator: {name}")
        ids[name] = matches[0]["id"]
    existing = get("evaluation-rules")
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
