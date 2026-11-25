"""retrieval / moments responsibilities."""
from __future__ import annotations

from app.indexing.scenes import scene_collection
from app.models.retrieval import encode_query
from app.models.retrieval import reranker
from app.observability import observation as _observe
from app.observability import update as _update
from app.pipelines.config import ResolvedPipelineConfig
from app.retrieval.queries import _prompted
from app.retrieval.search import _complete_names
from app.retrieval.search import passage_position
from app.retrieval.search import query_points_cached
from qdrant_client import QdrantClient
from qdrant_client import models
from typing import Any
import re



def moment_scene_hits(question: str, config: ResolvedPipelineConfig, collection: str, qdrant: QdrantClient,
                       evidence: list[dict[str, Any]], present: set[str]
                       ) -> tuple[list[dict[str, Any]], str]:
    """Passages of the scene that shows the moment the question asks about ("... when they first met in her house"),
    chosen by the generation model among the scenes whose summaries best match that moment. Returns them and the moment.

    A detail asked about at a moment (what someone wore, said or held) is often in a passage that names neither the
    people nor the moment, and the whole question matches the moment's scene poorly because it also describes the
    detail. So the moment is written out on its own and searched for, and the model reads the summaries found, in
    reading order, to choose (the cross-encoder cannot tell which of several similar scenes is the first one). The
    chosen window and the window that continues it are added, so a detail just past the window's end is kept. Nothing
    is added when the question names no moment, no summary shows it, or the evidence already holds a passage of it.
    """
    with _observe("moment description", input=question) as obs:
        reply = _prompted("scene_moment_system", question, config, "moment description")
        # The reply also states the detail asked for (DETAIL: ...); asking for it separately keeps it out of the moment.
        moment = next((line.partition(":")[2].strip().strip('"') for line in reply.splitlines()
                       if line.strip().upper().startswith("MOMENT:")), "")
        if moment.casefold().rstrip(".") == "none":
            moment = ""
        # Summaries name people the way the books do, so a bare first name is completed as in retrieval.
        if moment and config.name_completion:
            moment = _complete_names(moment, collection)
        _update(obs, output=moment or None)
    if not moment:
        return [], moment
    name = scene_collection(collection, config)
    vector = encode_query(moment, config.embedding_model.name, config.embedding_model.revision)
    found = query_points_cached(qdrant, name, vector, config.scene_search_hits, moment)
    if not found:
        return [], moment
    first = {str(point.id): dict(point.payload or {}) for point in qdrant.retrieve(
        collection_name=collection, ids=[scene.payload["members"][0] for scene in found], with_payload=True)}
    found.sort(key=lambda scene: passage_position(first[scene.payload["members"][0]]))
    listing = "\n\n".join(f"[{n}] {first[scene.payload['members'][0]].get('book')}, {first[scene.payload['members'][0]].get('chapter') or 'chapter unknown'}: "
                          f"{scene.payload['summary']}" for n, scene in enumerate(found, 1))
    with _observe("moment scene choice", input={"moment": moment, "scenes": listing}) as obs:
        reply = _prompted("scene_select_system", f"Moment: {moment}\n\nScenes:\n{listing}", config,
                          "moment scene choice")
        number = re.fullmatch(r"\W*(\d+)\W*", reply)
        chosen = found[int(number[1]) - 1] if number and 1 <= int(number[1]) <= len(found) else None
        _update(obs, output=chosen.payload["summary"] if chosen else None)
    if chosen is None:
        return [], moment
    # The windows holding the chosen window's last passage are that window and the one that continues it.
    following, _ = qdrant.scroll(collection_name=name, limit=100, with_payload=True, scroll_filter=models.Filter(
        must=[models.FieldCondition(key="members", match=models.MatchAny(any=[chosen.payload["members"][-1]]))]))
    span = list(dict.fromkeys([*chosen.payload["members"], *(member for scene in following for member in scene.payload["members"])]))
    if set(span) & {row["id"] for row in evidence}:
        return [], moment
    rows = sorted((dict(point.payload or {}) | {"id": str(point.id), "scene_hit": True, "moment_hit": True, "moment": moment,
                                                "scene_summary": chosen.payload["summary"]}
                   for point in qdrant.retrieve(collection_name=collection, ids=[member for member in span if member not in present], with_payload=True)),
                  key=passage_position)
    for row, score in zip(rows, reranker(config.reranker_model.name, config.reranker_model.revision).predict(
            [(question, row["text"]) for row in rows], show_progress_bar=False)):
        row["rerank_score"] = float(score)
    return rows, moment

