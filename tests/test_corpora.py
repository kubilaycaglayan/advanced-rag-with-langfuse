"""Corpus selection, isolation, and optional integrations."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import indexer
from app.corpus_config import corpus_config, corpus_data_dir
from app.corpus_profiles import agent_prompt, langfuse_enabled, load_profile, profile_prompt
from app.pipeline_resolver import resolve
from app.resolved_config import ResolvedPipelineConfig
from app.seed_dataset import default_seed_path


class _Encoder:
    def encode(self, texts, **kwargs):
        class VectorBatch(list):
            def tolist(self):
                return list(self)
        return VectorBatch([[0.25, 0.75] for _ in texts])


class _Qdrant:
    def __init__(self):
        self.collections = set()
        self.points = {}

    def collection_exists(self, name):
        return name in self.collections

    def create_collection(self, collection_name, **kwargs):
        self.collections.add(collection_name)

    def upsert(self, collection_name, points, **kwargs):
        self.points.setdefault(collection_name, []).extend(points)

    def count(self, collection_name, exact=True):
        return SimpleNamespace(count=len(self.points.get(collection_name, [])))


class CorpusChecks(unittest.TestCase):
    def test_millennium_keeps_its_three_books_and_profile(self):
        config = corpus_config()
        self.assertEqual(config.id, "millennium")
        self.assertEqual(len(list(config.books.glob("*.epub"))), 3)
        self.assertEqual(load_profile().id, "millennium")
        self.assertIn("Stieg Larsson's Millennium novels", profile_prompt("query_translation_system", ""))
        self.assertIn("Start with a search", agent_prompt())

    def _corpus(self, root: Path, corpus_id: str, books: dict[str, bytes]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "books").mkdir()
        (root / "corpus.yaml").write_text(
            f"id: {corpus_id}\ntitle: Test\nlanguage: en\nprofile: millennium\nbooks: books\nquestion_sets: {{}}\n",
            encoding="utf-8",
        )
        for name, body in books.items():
            (root / "books" / name).write_bytes(body)

    def test_one_book_corpus_resolves_profile_and_indexes_isolated_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "one-book"
            self._corpus(root, "one-book", {"book.epub": b"one local book"})
            env = {"CORPUS_ID": "one-book", "CORPUS_ROOT": str(root),
                   "EXPERIMENT_DATA_DIR": str(base / "data"), "LANGFUSE_ENABLED": "false"}
            with patch.dict(os.environ, env):
                os.environ.pop("CORPUS_DIR", None)
                self.assertEqual(corpus_config().id, "one-book")
                self.assertEqual(load_profile().id, "millennium")
                self.assertEqual(corpus_data_dir(), base / "data" / "one-book")
                resolved = resolve("v2.7")
                self.assertEqual(resolved.corpus_id, "one-book")
                self.assertEqual(resolved.profile_id, "millennium")
                self.assertTrue(resolved.index["collection"].startswith("one-book_books_"))

                config = ResolvedPipelineConfig(scene_margin=None, scene_context=False,
                                                entity_names=False, entity_matrix=False, entity_graph=False)
                qdrant = _Qdrant()
                row = {"book": "Test", "book_file": "book.epub", "section": "chapter.xhtml",
                       "paragraph": 1, "part": 1, "text": "A paragraph from one book."}
                with patch.object(indexer, "_passages", return_value=[row]), \
                     patch.object(indexer, "get_ready_manifest", return_value=None), \
                     patch.object(indexer, "get_index_manifest", return_value=None), \
                     patch.object(indexer, "save_index_manifest"), \
                     patch.object(indexer, "SentenceTransformer", return_value=_Encoder()):
                    result = indexer.build_index(config, qdrant)
                self.assertEqual(result["collection"], resolved.index["collection"] if config == resolved.config else indexer.index_identity(config)[0])
                self.assertEqual(result["passages_indexed"], 1)

    def test_same_source_is_isolated_between_corpus_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first, second = base / "first", base / "second"
            self._corpus(first, "first", {"same.epub": b"same source"})
            self._corpus(second, "second", {"same.epub": b"same source"})
            collections = []
            for corpus_id, root in (("first", first), ("second", second)):
                with patch.dict(os.environ, {"CORPUS_ID": corpus_id, "CORPUS_ROOT": str(root)}):
                    os.environ.pop("CORPUS_DIR", None)
                    collections.append(indexer.index_identity(ResolvedPipelineConfig())[0])
                    resolved = resolve("v2.6")
                    self.assertEqual(resolved.corpus_id, corpus_id)
                    self.assertTrue(resolved.corpus_checksum)
                    self.assertEqual(resolved.version_fields["corpus_id"], corpus_id)
                    self.assertEqual(resolved.version_fields["profile_id"], "millennium")
            self.assertNotEqual(collections[0], collections[1])

    def test_langfuse_can_be_disabled_without_affecting_corpus_loading(self):
        with patch.dict(os.environ, {"LANGFUSE_ENABLED": "false", "LANGFUSE_PUBLIC_KEY": "pk-test",
                                    "LANGFUSE_SECRET_KEY": "sk-test"}):
            self.assertFalse(langfuse_enabled())
            self.assertEqual(corpus_config().id, "millennium")

    def test_legacy_tracing_toggle_still_disables_langfuse(self):
        with patch.dict(os.environ, {"LANGFUSE_TRACING_ENABLED": "false", "LANGFUSE_PUBLIC_KEY": "pk-test",
                                    "LANGFUSE_SECRET_KEY": "sk-test"}):
            os.environ.pop("LANGFUSE_ENABLED", None)
            self.assertFalse(langfuse_enabled())

    def test_corpus_metadata_rejects_paths_outside_the_corpus(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "safe"
            root.mkdir()
            (root / "corpus.yaml").write_text(
                "id: safe\nquestion_sets:\n  unsafe:\n    path: ../outside.csv\n", encoding="utf-8")
            with patch.dict(os.environ, {"CORPUS_ID": "safe", "CORPUS_ROOT": str(root)}):
                with self.assertRaisesRegex(ValueError, "stay inside"):
                    corpus_config()

    def test_seed_path_comes_from_the_selected_question_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "custom-questions.csv").write_text("Question,Answer\nWho?,Someone\n", encoding="utf-8")
            (root / "corpus.yaml").write_text(
                "id: questions\nprofile: millennium\nquestion_sets:\n"
                "  Local name:\n    path: custom-questions.csv\n    langfuse_dataset: Hosted name\n"
                "langfuse:\n  default_dataset: Local name\n", encoding="utf-8")
            with patch.dict(os.environ, {"CORPUS_ID": "questions", "CORPUS_ROOT": str(root)}):
                self.assertEqual(default_seed_path(), root / "custom-questions.csv")
                self.assertEqual(default_seed_path("Hosted name"), root / "custom-questions.csv")


if __name__ == "__main__":
    unittest.main()
