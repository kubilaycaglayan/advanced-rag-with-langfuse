"""answering / cache_identity responsibilities."""
from __future__ import annotations

from app.cache import answers as answer_cache
from app.corpus_config import langfuse_project
from app.pipelines.resolver import ResolvedRun
from typing import Any



def _answer_cache_identity(question: str, resolved: ResolvedRun, collection: str) -> dict[str, Any]:
    return answer_cache.identity(
        project_id=langfuse_project(), corpus_id=resolved.corpus_id,
        pipeline_version=resolved.version, pipeline_fingerprint=resolved.fingerprint,
        pipeline_id=resolved.pipeline_id, corpus_checksum=resolved.corpus_checksum,
        profile_id=resolved.profile_id, profile_identity=resolved.profile_identity,
        prompt_identity=resolved.prompt_identity, collection=collection, question=str(question),
        config=resolved.config.manifest(),
        agent_settings=(resolved.agent_settings.__dict__ if resolved.agent_settings else None))

