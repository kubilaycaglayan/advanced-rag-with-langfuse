"""experiments / datasets responsibilities."""
from __future__ import annotations

from app.corpus_config import langfuse_dataset_name
from app.corpus_config import langfuse_project
from app.identity import question_session_id
from datetime import datetime
from datetime import timezone
from langfuse import Langfuse
from typing import Any
import os


def _item_question(item: Any) -> Any:
    return item.input.get("question") if isinstance(item.input, dict) else item.input


def _item_session(dataset_name: str, item: Any) -> str:
    return question_session_id(dataset_name, item.id, item.metadata, _item_question(item))


def _dataset_for(payload: dict[str, Any], client: Langfuse) -> tuple[Any, datetime]:
    name = langfuse_dataset_name(payload.get("dataset_name") or os.getenv("DATASET_NAME"))
    supplied_version = payload.get("dataset_version")
    version = datetime.fromisoformat(supplied_version.replace("Z", "+00:00")) if supplied_version else None
    if version is not None and version.utcoffset() is None:
        raise ValueError("dataset_version must be an ISO-8601 timezone-aware timestamp")
    if version is None:
        latest = client.get_dataset(name)
        # SDK 4.17 does not expose the resolved "latest" item snapshot timestamp.
        # Pin the dataset's server update timestamp and refetch through its historical
        # version adapter before materializing any experiment items.
        timestamps = [latest.updated_at]
        timestamps.extend(item.updated_at for item in latest.items if getattr(item, "updated_at", None) is not None)
        version = max(timestamps)
        if version.utcoffset() is None:
            version = version.replace(tzinfo=timezone.utc)
    dataset = client.get_dataset(name, version=version)
    if payload.get("dataset_id") and payload["dataset_id"] != dataset.id:
        raise ValueError("trigger dataset_id does not match dataset_name")
    projects = getattr(client.api.projects.get(), "data", []) or []
    matches = [project for project in projects if project.name == langfuse_project() and project.id == dataset.project_id]
    if len(matches) != 1:
        raise RuntimeError(f"dataset does not belong to configured Langfuse project {langfuse_project()!r}")
    resolved_version = dataset.version or version
    if resolved_version.utcoffset() is None:
        resolved_version = resolved_version.replace(tzinfo=timezone.utc)
    return dataset, resolved_version.astimezone(timezone.utc)

