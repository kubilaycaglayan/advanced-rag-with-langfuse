"""Build and validate isolated Qdrant collections from corpus/config manifests."""
from __future__ import annotations

import hashlib
import inspect
import os
import re
import uuid
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

try:
    from .experiment_store import get_index_manifest, get_ready_manifest, save_index_manifest
    from .identity import canonical_json
    from .resolved_config import ResolvedPipelineConfig
    from .entities import build_entity_cards, entity_cards_path
    from .scenes import build_scene_index, scene_collection
except ImportError:
    from experiment_store import get_index_manifest, get_ready_manifest, save_index_manifest
    from identity import canonical_json
    from resolved_config import ResolvedPipelineConfig
    from entities import build_entity_cards, entity_cards_path
    from scenes import build_scene_index, scene_collection

SPLITTER_VERSION = "sentence-word-splitter-v1"


def corpus_paths() -> list[Path]:
    directory = Path(os.getenv("CORPUS_DIR", str(Path(__file__).resolve().parents[1] / "corpus")))
    return sorted(directory.glob("*.epub"))


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        pieces = [sentence]
        if len(sentence) > limit:
            pieces, buf = [], ""
            for word in sentence.split():
                candidate = f"{buf} {word}".strip()
                if buf and len(candidate) > limit:
                    pieces.append(buf)
                    buf = word
                else:
                    buf = candidate
            if buf:
                pieces.append(buf)
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def _chapter_titles(book: epub.EpubBook) -> dict[str, str]:
    result: dict[str, str] = {}
    def visit(items: Any) -> None:
        for item in items:
            if isinstance(item, tuple):
                visit([item[0]])
                visit(item[1])
            else:
                href, title = getattr(item, "href", ""), getattr(item, "title", "")
                if href and title:
                    result[href.split("#", 1)[0]] = str(title).strip()
    visit(book.toc)
    return result


def _page_marker(element: Any) -> str | None:
    epub_type = element.attrs.get("epub:type", "")
    role = str(element.attrs.get("role", ""))
    classes = str(element.attrs.get("class", ""))
    if "pagebreak" not in f"{epub_type} {role}".lower() and "page" not in classes.lower():
        return None
    label = element.attrs.get("title") or element.attrs.get("aria-label") or element.attrs.get("id")
    if label:
        match = re.search(r"\d+", str(label))
        return match.group(0) if match else str(label)
    return None


def _splitter_fingerprint() -> str:
    implementation = SPLITTER_VERSION + "".join(inspect.getsource(function) for function in (_split, _chapter_titles, _page_marker, _extract))
    return hashlib.sha256(implementation.encode("utf-8")).hexdigest()


def _extract(path: Path, limit: int) -> list[dict[str, Any]]:
    book = epub.read_epub(str(path))
    title_meta = book.get_metadata("DC", "title")
    title = title_meta[0][0] if title_meta else path.stem
    toc = _chapter_titles(book)
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    current_page: str | None = None
    started = False
    for idref, _linear in book.spine:
        document = book.get_item_with_id(idref)
        if document is None or document.get_type() != ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(document.get_content(), "html.parser")
        headings = [re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() for node in soup.find_all(["h1", "h2", "h3", "p"])]
        explicit = next((heading for heading in headings if re.match(r"^(PROLOGUE|EPILOGUE|CHAPTER\s+\d+|PART\s+\d+)\b", heading, re.I)), None)
        chapter = explicit or toc.get(document.file_name) or toc.get(Path(document.file_name).name)
        if not started:
            if explicit and re.match(r"^(PROLOGUE|CHAPTER\s+1)\b", explicit, re.I):
                started = True
            else:
                continue
        for node in soup.find_all(True):
            marker = _page_marker(node)
            if marker:
                current_page = marker
            if node.name not in {"p", "div"}:
                continue
            if node.name == "div" and node.find(["p", "div"]):
                continue
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if len(text) < 2:
                continue
            counts[document.file_name] = counts.get(document.file_name, 0) + 1
            for part, chunk in enumerate(_split(text, limit), 1):
                rows.append({"book": title, "book_file": path.name, "section": document.file_name,
                             "paragraph": counts[document.file_name], "part": part, "chapter": chapter, "page": current_page,
                             "text": chunk})
    return rows


def _merge(rows: list[dict[str, Any]], min_chars: int, max_chars: int, overlap: int) -> list[dict[str, Any]]:
    """Join consecutive passages of one EPUB section until a passage reaches min_chars.

    A passage never grows past max_chars by joining; ``overlap`` trailing units of each
    passage are repeated at the start of the next one in the same section.
    """
    merged: list[dict[str, Any]] = []

    def emit(units: list[dict[str, Any]]) -> None:
        first, last = units[0], units[-1]
        merged.append(first | {"paragraph_end": last["paragraph"], "part_end": last["part"],
                               "text": "\n".join(unit["text"] for unit in units)})

    window: list[dict[str, Any]] = []
    fresh = 0  # units in the window not carried over from the previous passage
    for row in rows:
        if window and (window[0]["book_file"], window[0]["section"]) != (row["book_file"], row["section"]):
            if fresh:
                emit(window)
            window, fresh = [], 0
        size = sum(len(unit["text"]) + 1 for unit in window)
        if window and fresh and (size >= min_chars or size + len(row["text"]) > max_chars):
            emit(window)
            window = window[len(window) - min(overlap, len(window) - 1):] if overlap else []
            fresh = 0
        while window and sum(len(unit["text"]) + 1 for unit in window) + len(row["text"]) > max_chars:
            window.pop(0)
        window.append(row)
        fresh += 1
    if window and fresh:
        emit(window)
    return merged


def _merge_settings(config: ResolvedPipelineConfig) -> dict[str, Any] | None:
    if not config.min_passage_chars:
        return None
    return {"min_passage_chars": config.min_passage_chars, "passage_overlap": config.passage_overlap,
            "merge_fingerprint": hashlib.sha256(inspect.getsource(_merge).encode("utf-8")).hexdigest()}


def _passages(path: Path, config: ResolvedPipelineConfig) -> list[dict[str, Any]]:
    rows = _extract(path, config.passage_chars)
    if config.min_passage_chars:
        rows = _merge(rows, config.min_passage_chars, config.passage_chars, config.passage_overlap)
    return rows


def index_identity(config: ResolvedPipelineConfig) -> tuple[str, str, dict[str, Any], dict[str, str]]:
    paths = corpus_paths()
    if len(paths) != 3:
        raise RuntimeError(f"expected exactly three EPUBs in {paths[0].parent if paths else os.getenv('CORPUS_DIR', 'corpus')}, found {len(paths)}")
    corpus = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    corpus_checksum = hashlib.sha256(canonical_json(corpus).encode()).hexdigest()
    model_id = config.embedding_model.name
    splitter_fingerprint = _splitter_fingerprint()
    manifest = {"corpus": corpus, "corpus_checksum": corpus_checksum, "passage_chars": config.passage_chars,
                "splitter": SPLITTER_VERSION, "splitter_fingerprint": splitter_fingerprint,
                "embedding_model": config.embedding_model.__dict__,
                "vector_settings": {"distance": "cosine", "normalized": True}}
    merge = _merge_settings(config)
    if merge:
        # Added only when enabled so existing unmerged index identities stay valid.
        manifest["merge"] = merge
    fingerprint = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    collection = "millennium_books_" + fingerprint[:20]
    return collection, fingerprint, manifest, corpus


def build_index(config: ResolvedPipelineConfig, qdrant: QdrantClient | None = None, *, explicit_rebuild: bool = False) -> dict[str, Any]:
    qdrant = qdrant or QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)
    result = _build_passage_index(config, qdrant, explicit_rebuild=explicit_rebuild)
    if config.scene_margin is not None:
        encoder = SentenceTransformer(config.embedding_model.name, device="cpu", revision=config.embedding_model.revision)
        result["scenes"] = build_scene_index(result["collection"], config, qdrant, encoder)
    if config.entity_names:
        result["entities"] = build_entity_cards(result["collection"], config, qdrant)
    return result


def _build_passage_index(config: ResolvedPipelineConfig, qdrant: QdrantClient, *, explicit_rebuild: bool = False) -> dict[str, Any]:
    collection, fingerprint, manifest, corpus = index_identity(config)
    paths = corpus_paths()
    model_id = config.embedding_model.name
    prior = get_ready_manifest(collection, fingerprint)
    if prior:
        if not qdrant.collection_exists(collection):
            raise RuntimeError(f"ready index manifest points to missing Qdrant collection {collection}")
        count = qdrant.count(collection_name=collection, exact=True).count
        if count != prior["actual_point_count"]:
            raise RuntimeError(f"index point count mismatch for {collection}: manifest={prior['actual_point_count']}, qdrant={count}")
        return {"collection": collection, "fingerprint": fingerprint, "passages_indexed": count, "already_indexed": True}

    incomplete = get_index_manifest(collection, fingerprint)
    if incomplete and not explicit_rebuild:
        raise RuntimeError(f"index {collection} has state {incomplete['state']}; explicit rebuild is required")
    if incomplete and explicit_rebuild and qdrant.collection_exists(collection):
        qdrant.delete_collection(collection)

    rows = [row for path in paths for row in _passages(path, config)]
    if not rows:
        raise RuntimeError("EPUB extraction produced no passages")
    save_index_manifest(collection=collection, fingerprint=fingerprint, config=manifest, corpus=corpus,
                        splitter_fingerprint=manifest["splitter_fingerprint"], embedding_identity=model_id,
                        vector_settings=manifest["vector_settings"], expected=len(rows), actual=0, state="building")
    try:
        encoder = SentenceTransformer(model_id, device="cpu", revision=config.embedding_model.revision)
        vectors = encoder.encode([row["text"] for row in rows], batch_size=64, show_progress_bar=False,
                                 normalize_embeddings=True).tolist()
        if not qdrant.collection_exists(collection):
            qdrant.create_collection(collection_name=collection, vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE))
        points = []
        for row, vector in zip(rows, vectors):
            identity = hashlib.sha256(canonical_json({"book_file": row["book_file"], "section": row["section"], "paragraph": row["paragraph"], "part": row["part"], "text": row["text"]}).encode()).hexdigest()
            points.append(models.PointStruct(id=str(uuid.UUID(identity[:32])), vector=vector, payload={**row, "embedding_model": model_id, "source_id": identity}))
        for start in range(0, len(points), 128):
            qdrant.upsert(collection_name=collection, points=points[start:start+128], wait=True)
        count = qdrant.count(collection_name=collection, exact=True).count
        if count != len(points):
            raise RuntimeError(f"Qdrant count verification failed: expected {len(points)}, got {count}")
        save_index_manifest(collection=collection, fingerprint=fingerprint, config=manifest, corpus=corpus,
                            splitter_fingerprint=manifest["splitter_fingerprint"], embedding_identity=model_id,
                            vector_settings=manifest["vector_settings"], expected=len(points), actual=count, state="ready")
        return {"collection": collection, "fingerprint": fingerprint, "passages_indexed": count, "already_indexed": False}
    except Exception:
        try:
            actual = qdrant.count(collection_name=collection, exact=True).count if qdrant.collection_exists(collection) else 0
        except Exception:
            actual = 0
        save_index_manifest(collection=collection, fingerprint=fingerprint, config=manifest, corpus=corpus,
                            splitter_fingerprint=manifest["splitter_fingerprint"], embedding_identity=model_id,
                            vector_settings=manifest["vector_settings"], expected=len(rows), actual=actual, state="failed")
        raise


def validate_index(collection: str, config: ResolvedPipelineConfig, qdrant: QdrantClient | None = None) -> dict[str, Any]:
    expected_collection, fingerprint, manifest, corpus = index_identity(config)
    if collection != expected_collection:
        raise RuntimeError(f"collection {collection!r} does not match requested index identity {expected_collection!r}")
    row = get_ready_manifest(collection, fingerprint)
    if row is None:
        raise RuntimeError(f"no ready index manifest matches collection={collection!r} and requested config")
    qdrant = qdrant or QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)
    if not qdrant.collection_exists(collection):
        raise RuntimeError(f"ready index collection {collection!r} is unavailable")
    count = qdrant.count(collection_name=collection, exact=True).count
    if count != row["actual_point_count"] or count != row["expected_point_count"]:
        raise RuntimeError(f"index point count mismatch: expected={row['expected_point_count']} actual={count}")
    if config.scene_margin is not None and not qdrant.collection_exists(scene_collection(collection, config)):
        raise RuntimeError(f"scene search is on but the scene index for {collection!r} is not built")
    if config.entity_names and not entity_cards_path(collection, config).exists():
        raise RuntimeError(f"entity names are on but the entity cards for {collection!r} are not built")
    return row
