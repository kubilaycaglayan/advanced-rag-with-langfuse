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

    def test_short_section_end_joins_the_passage_before_it(self):
        merged = _merge(rows("a" * 8, "b" * 8, "cc") + rows("dddddddd", section="s2"), min_chars=8, max_chars=100, overlap=0)
        self.assertEqual([m["text"] for m in merged], ["a" * 8, "b" * 8 + "\ncc", "dddddddd"])
        self.assertEqual((merged[1]["paragraph"], merged[1]["paragraph_end"]), (2, 3))

    def test_short_section_end_that_cannot_join_takes_the_last_units_before_it(self):
        merged = _merge(rows("a" * 5, "b" * 5, "c" * 5, "dd"), min_chars=11, max_chars=14, overlap=0)
        self.assertEqual([m["text"] for m in merged], ["a" * 5 + "\n" + "b" * 5, "b" * 5 + "\n" + "c" * 5 + "\ndd"])

    def test_short_section_alone_and_overlapping_end_are_not_repeated(self):
        self.assertEqual([m["text"] for m in _merge(rows("cc"), min_chars=8, max_chars=100, overlap=0)], ["cc"])
        merged = _merge(rows("aaaa", "bbbb", "c"), min_chars=8, max_chars=100, overlap=1)
        self.assertEqual([m["text"] for m in merged], ["aaaa\nbbbb\nc"])

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
        self.assertTrue(ResolvedPipelineConfig.from_mapping({"answer_thinking": True}).answer_thinking)
        for bad in ({"expansion_count": 0}, {"min_passage_chars": 0, "passage_overlap": 1}, {"min_passage_chars": -1}, {"answer_thinking": "yes"}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def test_not_found_in_sources_is_an_abstention(self):
        self.assertTrue(is_explicit_abstention("The information was not found in the sources."))
        self.assertFalse(is_explicit_abstention("Salander's mother is Agneta Sofia Salander [E5]."))


if __name__ == "__main__":
    unittest.main()
