"""Paragraph merging, overlap, and tuning-setting validation."""
import os
import unittest
from unittest.mock import patch

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app.evaluation import is_explicit_abstention
from app.indexer import _merge, index_identity
from app.resolved_config import ResolvedPipelineConfig


def rows(*texts, section="s1"):
    return [{"book_file": "b.epub", "section": section, "paragraph": i, "part": 1, "text": t}
            for i, t in enumerate(texts, 1)]


class ChunkingChecks(unittest.TestCase):
    def test_merges_short_paragraphs_up_to_minimum(self):
        merged = _merge(rows("aaaa", "bbbb", "cccc", "dddd"), min_chars=8, max_chars=100, overlap=0)
        self.assertEqual([m["text"] for m in merged], ["aaaa\nbbbb", "cccc\ndddd"])
        self.assertEqual((merged[0]["paragraph"], merged[0]["paragraph_end"]), (1, 2))

    def test_never_joins_past_maximum_or_across_sections(self):
        merged = _merge(rows("a" * 6, "b" * 6) + rows("cc", section="s2"), min_chars=20, max_chars=10, overlap=0)
        self.assertEqual([m["text"] for m in merged], ["a" * 6, "b" * 6, "cc"])

    def test_overlap_repeats_trailing_paragraphs(self):
        merged = _merge(rows("aaaa", "bbbb", "cccc", "dddd"), min_chars=8, max_chars=100, overlap=1)
        self.assertEqual([m["text"] for m in merged], ["aaaa\nbbbb", "bbbb\ncccc", "cccc\ndddd"])

    def test_merge_changes_index_identity_only_when_enabled(self):
        with patch("app.indexer.corpus_paths") as paths:
            paths.return_value = [type("P", (), {"name": n, "read_bytes": lambda self: b"x", "parent": "c"})() for n in "abc"]
            plain = index_identity(ResolvedPipelineConfig(min_passage_chars=0))
            merged = index_identity(ResolvedPipelineConfig(min_passage_chars=400))
        self.assertNotIn("merge", plain[2])
        self.assertNotEqual(plain[0], merged[0])

    def test_tuning_settings_are_validated(self):
        self.assertEqual(ResolvedPipelineConfig.from_mapping({"expansion_count": 5}).expansion_count, 5)
        self.assertEqual(ResolvedPipelineConfig().min_passage_chars, 400)
        for bad in ({"expansion_count": 0}, {"min_passage_chars": 0, "passage_overlap": 1}, {"min_passage_chars": -1}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def test_not_found_in_sources_is_an_abstention(self):
        self.assertTrue(is_explicit_abstention("The information was not found in the sources."))
        self.assertFalse(is_explicit_abstention("Salander's mother is Agneta Sofia Salander [E5]."))


if __name__ == "__main__":
    unittest.main()
