"""Unit checks for the qm_ quality-metric extraction and precision scoring."""
import json
import unittest
from types import SimpleNamespace

from app.quality_metrics import SearchCall, _context_text, _precision_at, extract_trace, faithfulness_context


class QualityMetricChecks(unittest.TestCase):
    def test_precision_at_k_uses_the_requested_cutoff(self):
        call = SearchCall(observation_id="obs", tool="tool: semantic_search", query="q",
                          hit_ids=["a", "b", "c", "d", "e"])
        self.assertEqual(_precision_at(call, {"a", "c", "x"}, 5), 0.4)
        self.assertIsNone(_precision_at(call, {"a", "c"}, 10))

    def test_extract_trace_keeps_ranked_hits_read_passages_and_answer(self):
        observations = [
            SimpleNamespace(id="search", name="tool: semantic_search", output=json.dumps({
                "query": "q", "hits": [{"id": "11111111", "text": "one"},
                                        {"id": "22222222", "text": "two"}]})),
            SimpleNamespace(id="read", name="tool: read_passage", output=json.dumps({
                "passage": {"id": "33333333", "text": "three"},
                "neighbours": [{"id": "44444444", "text": "four"}]})),
            SimpleNamespace(id="root", name="experiment-item-task", output=json.dumps({
                "answer": "Yes.", "evidence": [{"id": "55555555", "text": "five"}]})),
        ]
        calls, union_ids, texts, answer, locations = extract_trace(observations)
        self.assertEqual(answer, "Yes.")
        self.assertEqual([call.hit_ids for call in calls], [["11111111", "22222222"]])
        self.assertEqual(union_ids, {"11111111", "22222222", "33333333", "44444444", "55555555"})
        self.assertEqual(texts["44444444"], "four")


    def test_extract_trace_prefers_full_read_text_over_a_search_snippet(self):
        observations = [
            SimpleNamespace(id="search", name="tool: semantic_search", output=json.dumps({
                "query": "q", "hits": [{"id": "11111111", "text": "short snippet"}]})),
            SimpleNamespace(id="read", name="tool: read_passage", output=json.dumps({
                "passage": {"id": "11111111", "text": "the full passage text"},
                "neighbours": []})),
        ]
        _, _, texts, _, _ = extract_trace(observations)
        self.assertEqual(texts["11111111"], "the full passage text")

    def test_faithfulness_uses_recorded_model_input_not_trace_evidence(self):
        root = SimpleNamespace(name="agent run", output={"stopped": "submit"})
        generation = SimpleNamespace(name="query agent model: tool selection and answer", start_time=1,
                                     input=json.dumps([{"role": "tool", "content": "actual snippet"}]))
        extra = SimpleNamespace(name="tool: read_passage", output={"passage": {"text": "unseen text"}})
        self.assertEqual(faithfulness_context([root, generation, extra]), ("actual snippet", None))

    def test_faithfulness_rejects_oversize_and_rewritten_context(self):
        root = SimpleNamespace(name="agent run", output={"stopped": "submit"})
        generation = SimpleNamespace(name="query agent model: tool selection and answer", start_time=1,
                                     input=[{"role": "tool", "content": "x" * 12001}])
        self.assertIsNone(faithfulness_context([root, generation])[0])
        self.assertIsNone(faithfulness_context([root, generation, SimpleNamespace(name="coverage rewrite")])[0])

    def test_context_text_marks_each_passage_with_its_id(self):
        text = _context_text({"a", "b"}, {"a": "first", "b": "second"})
        self.assertEqual(text, "[a] first\n\n[b] second")


if __name__ == "__main__":
    unittest.main()
