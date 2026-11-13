"""Unit checks for the qm_ quality-metric extraction and precision scoring."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.quality_metrics import SearchCall, _context_text, _precision_at, _ollama_json, extract_trace, faithfulness_context, score_trace


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

    def test_faithfulness_accepts_long_context_but_rejects_rewritten_context(self):
        root = SimpleNamespace(name="agent run", output={"stopped": "submit"})
        generation = SimpleNamespace(name="query agent model: tool selection and answer", start_time=1,
                                     input=[{"role": "tool", "content": "x" * 12001}])
        self.assertEqual(faithfulness_context([root, generation])[0], "x" * 12001)
        self.assertIsNone(faithfulness_context([root, generation, SimpleNamespace(name="coverage rewrite")])[0])

    @patch("app.quality_metrics.requests.post")
    def test_judge_expands_context_for_long_inputs_and_rejects_oversize(self, post):
        post.return_value.json.return_value = {"message": {"content": "{}"}}
        _ollama_json([{"role": "user", "content": "x" * 35000}], {}, "judge")
        self.assertEqual(post.call_args.kwargs["json"]["options"]["num_ctx"], 65536)
        with self.assertRaisesRegex(ValueError, "maximum safe context"):
            _ollama_json([{"role": "user", "content": "x" * 262144}], {}, "judge")

    def test_context_text_marks_each_passage_with_its_id(self):
        text = _context_text({"a", "b"}, {"a": "first", "b": "second"})
        self.assertEqual(text, "[a] first\n\n[b] second")

    def test_scores_are_attached_to_timed_child_observations(self):
        client = MagicMock()
        stack = []
        spans = {}

        @contextmanager
        def start(*, name, **kwargs):
            span = MagicMock()
            spans[name] = (span, stack[-1] if stack else None)
            stack.append(name)
            try:
                yield span
            finally:
                stack.pop()

        client.start_as_current_observation.side_effect = start
        observations = [
            SimpleNamespace(id="root", name="experiment-item-run", parent_observation_id=None, output={}),
            SimpleNamespace(id="search", name="tool: semantic_search", parent_observation_id="root",
                            output={"hits": [{"id": "12345678"}]}),
            SimpleNamespace(name="agent run", output={"stopped": "submit", "answer": "answer"}),
            SimpleNamespace(name="query agent model: tool selection and answer", start_time=1,
                            input=[{"role": "tool", "content": "evidence"}], output={}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qrels.json"
            path.write_text(json.dumps({"version": 4, "index_collection": "idx", "datasets": {
                "set": {"item": {"question": "question", "passages": [
                    {"short_id": "12345678", "relevance": "direct"}]}}}}))
            with patch("app.quality_metrics.Langfuse", return_value=client), \
                 patch("app.quality_metrics.fetch_observations", return_value=observations), \
                 patch("app.quality_metrics.judge_faithfulness", return_value={"score": 1.0}), \
                 patch("app.quality_metrics.judge_relevancy", return_value={"score": 0.8}):
                result = score_trace("trace", path, "set", "item", (1,), "judge", write=True)
        self.assertEqual(spans["retrieval evaluation"][1], "quality evaluation")
        self.assertEqual(spans["retrieval search call evaluation"][1], "retrieval evaluation")
        self.assertEqual(client.start_as_current_observation.call_args_list[0].kwargs["trace_context"],
                         {"trace_id": "trace", "parent_span_id": "root"})
        for name in ("faithfulness evaluation", "relevancy evaluation"):
            self.assertEqual(spans[name][1], "quality evaluation")
            kwargs = spans[name][0].score.call_args.kwargs
            self.assertGreaterEqual(kwargs["metadata"]["duration_seconds"], 0)
        self.assertEqual(result["metrics"]["qm_relevancy_generation"], 0.8)
        self.assertGreaterEqual(result["durations_seconds"]["total"], 0)

    def test_failed_judge_does_not_prevent_other_metrics(self):
        observations = [
            SimpleNamespace(name="agent run", output={"stopped": "submit", "answer": "answer"}),
            SimpleNamespace(name="query agent model: tool selection and answer", start_time=1,
                            input=[{"role": "tool", "content": "evidence"}], output={}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qrels.json"
            path.write_text(json.dumps({"datasets": {"set": {"item": {
                "question": "question", "passages": []}}}}))
            with patch("app.quality_metrics.Langfuse"), \
                 patch("app.quality_metrics.fetch_observations", return_value=observations), \
                 patch("app.quality_metrics.judge_faithfulness", side_effect=RuntimeError("judge unavailable")), \
                 patch("app.quality_metrics.judge_relevancy", return_value={"score": 0.8}):
                result = score_trace("trace", path, "set", "item", (1,), "judge", write=False)
        self.assertEqual(result["errors"], ["faithfulness"])
        self.assertIn("judge unavailable", result["faithfulness"]["reason"])
        self.assertEqual(result["metrics"]["qm_relevancy_generation"], 0.8)


if __name__ == "__main__":
    unittest.main()
