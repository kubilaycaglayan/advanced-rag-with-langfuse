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
        self.assertTrue(ResolvedPipelineConfig().name_completion)
        self.assertFalse(ResolvedPipelineConfig.from_mapping({"name_completion": False}).name_completion)
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
        self.assertEqual(config.wide_max_hits, 3)
        for bad in ({"wide_candidate_count": -1}, {"wide_candidate_count": 201}, {"wide_candidate_count": True}, {"wide_trigger_score": "x"},
                    {"wide_max_hits": -1}, {"wide_max_hits": 31}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def _run(self, scores, named_scores=None, **settings):
        # Each search returns p0..p5; the first three are fused candidates, p3..p5 form the wider pool.
        # The name-completed search ("q named") returns p6..p7 only.
        points = [MagicMock(id=f"p{i}", payload={"text": f"t{i}"}) for i in range(8)]
        client = MagicMock()
        client.query_points.side_effect = lambda **kw: MagicMock(points=points[6:] if kw["query"] == "q named" else points[:6])
        embedder = MagicMock()
        embedder.encode.side_effect = lambda text, normalize_embeddings: MagicMock(tolist=lambda: text)
        reranker = MagicMock()
        reranker.predict.side_effect = lambda pairs, show_progress_bar: [(named_scores if q == "q named" else scores)[text] for q, text in pairs]
        config = ResolvedPipelineConfig(**{"retrieval_mode": "query_expansion", "candidate_count": 3, "top_k": 3, "low_confidence_top_k": 3, "wide_candidate_count": 6} | settings)
        with patch.object(pipeline, "qdrant_client", return_value=client), patch.object(pipeline, "_embedder", return_value=embedder), \
                patch.object(pipeline, "_reranker", return_value=reranker), patch.object(pipeline, "_transform", return_value=(None, ["alt"], None)), \
                patch.object(pipeline, "_complete_names", return_value="q named" if named_scores else "q"), \
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
        # At most wide_max_hits passages are admitted, best first.
        self.assertEqual(self._run(base | {"t4": 3.2}, wide_max_hits=1)[0], ["p3", "p1", "p0", "p2"])

    def test_completed_name_scores_the_wider_pool(self):
        base = {"t0": 1.0, "t1": 1.5, "t2": 0.5, "t3": -1.0, "t4": -1.0, "t5": -1.0, "t6": -5.0, "t7": -5.0}
        named = {"t0": 2.0, "t1": 4.0, "t2": 1.0, "t3": 3.0, "t4": 0.0, "t5": 0.0, "t6": 6.0, "t7": 3.9}
        # p6 is found only by the completed wording and beats every fused candidate under it; p3 and p7 do not
        # beat the best fused candidate under the completed wording (4.0). The fused evidence is unchanged.
        self.assertEqual(self._run(base, named), (["p6", "p1", "p0", "p2"], True))
        self.assertEqual(self._run(base, named, name_completion=False), (["p1", "p0", "p2"], True))


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
