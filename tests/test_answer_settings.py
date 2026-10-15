"""Name completion and reasoning-answer fallback."""
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app import pipeline
from app.resolved_config import ResolvedPipelineConfig


class NameCompletionChecks(unittest.TestCase):
    def setUp(self):
        pipeline._name_pairs.cache_clear()

    def _pairs(self, texts):
        client = MagicMock()
        client.scroll.return_value = ([MagicMock(payload={"text": t}) for t in texts], None)
        with patch.object(pipeline, "qdrant_client", return_value=client):
            return pipeline._name_pairs("collection")

    def test_expands_dominant_full_name_only(self):
        pairs = self._pairs(["Mikael Blomkvist said. " * 30 + "Mikael Persson left. " * 3 + "Anna Berg and Anna Lind. " * 15
                             + "Then Blomkvist went. " * 100 + "Lisbeth Salander came. " * 30 + "Salander left. " * 200])
        with patch.object(pipeline, "_name_pairs", return_value=pairs):
            self.assertEqual(pipeline._complete_names("Who tried to shoot Mikael?", "c"), "Who tried to shoot Mikael Blomkvist?")
            # No single dominant name: left unchanged.
            self.assertEqual(pipeline._complete_names("Where is Anna?", "c"), "Where is Anna?")
            # Already complete: unchanged.
            self.assertEqual(pipeline._complete_names("Is Mikael Blomkvist here?", "c"), "Is Mikael Blomkvist here?")
            # The books mostly use "Salander" itself, so it is left as written.
            self.assertEqual(pipeline._complete_names("Where is Salander?", "c"), "Where is Salander?")

    def test_setting_is_validated(self):
        self.assertTrue(ResolvedPipelineConfig.from_mapping({"name_completion": True}).name_completion)
        with self.assertRaises(ValueError):
            ResolvedPipelineConfig.from_mapping({"name_completion": 1})


class LowConfidenceSettingChecks(unittest.TestCase):
    def test_defaults_and_validation(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.top_k, config.answer_thinking, config.low_confidence_score, config.low_confidence_top_k), (10, False, 2.0, 15))
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"low_confidence_score": None}).low_confidence_score)
        for bad in ({"low_confidence_score": "high"}, {"low_confidence_score": float("nan")}, {"low_confidence_top_k": 0}, {"low_confidence_top_k": 31}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)


class WideCandidateChecks(unittest.TestCase):
    def test_validation(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.wide_candidate_count, config.wide_trigger_score), (100, 3.5))
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"wide_trigger_score": None}).wide_trigger_score)
        for bad in ({"wide_candidate_count": -1}, {"wide_candidate_count": 201}, {"wide_candidate_count": True}, {"wide_trigger_score": "x"}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def _run(self, scores, **settings):
        # Each search returns p0..p5; the first three are fused candidates, p3..p5 form the wider pool.
        points = [MagicMock(id=f"p{i}", payload={"text": f"t{i}"}) for i in range(6)]
        client = MagicMock()
        client.query_points.return_value = MagicMock(points=points)
        reranker = MagicMock()
        reranker.predict.side_effect = lambda pairs, show_progress_bar: [scores[text] for _, text in pairs]
        config = ResolvedPipelineConfig(**{"retrieval_mode": "query_expansion", "candidate_count": 3, "top_k": 3, "low_confidence_top_k": 3, "wide_candidate_count": 6} | settings)
        with patch.object(pipeline, "qdrant_client", return_value=client), patch.object(pipeline, "_embedder"), \
                patch.object(pipeline, "_reranker", return_value=reranker), patch.object(pipeline, "_transform", return_value=(None, ["alt"], None)), \
                patch.object(pipeline, "_ollama", return_value="Answer [E1]."):
            result = pipeline.run_pipeline("q", config, collection="c")
        self.assertEqual(client.query_points.call_args.kwargs["limit"], max(3, config.wide_candidate_count))
        return [row["id"] for row in result["reranked"]], result["low_confidence"]

    def test_wide_passage_added_in_front_only_when_it_beats_fused_candidates(self):
        base = {"t0": 1.0, "t1": 3.0, "t2": 0.5, "t3": 4.0, "t4": 2.9, "t5": -1.0}
        # p3 beats every fused candidate and is a confident match: added before the unchanged evidence.
        self.assertEqual(self._run(base), (["p3", "p1", "p0", "p2"], False))
        # A strong fused match (>= wide_trigger_score) keeps the evidence unchanged.
        self.assertEqual(self._run(base | {"t1": 3.6}), (["p1", "p0", "p2"], False))
        self.assertEqual(self._run(base | {"t1": 3.6}, wide_trigger_score=None), (["p3", "p1", "p0", "p2"], False))
        # Beating the fused candidates is not enough below the low-confidence threshold.
        self.assertEqual(self._run(base | {"t1": 1.5, "t3": 1.9, "t4": 1.8}), (["p1", "p0", "p2"], True))
        # A wider pool no larger than candidate_count adds nothing.
        self.assertEqual(self._run(base, wide_candidate_count=3)[0], ["p1", "p0", "p2"])


class ThinkingFallbackChecks(unittest.TestCase):
    def test_empty_reasoning_answer_retries_without_thinking(self):
        calls = []

        def post(url, json, timeout):
            calls.append(json["think"])
            response = MagicMock()
            response.json.return_value = {"message": {"content": "" if json["think"] else "Answer [E1]."}}
            return response

        with patch.object(pipeline.requests, "post", side_effect=post):
            self.assertEqual(pipeline._ollama([{"role": "user", "content": "q"}], "m", (10, 20), think=True), "Answer [E1].")
        self.assertEqual(calls, [True, True, False])


if __name__ == "__main__":
    unittest.main()
