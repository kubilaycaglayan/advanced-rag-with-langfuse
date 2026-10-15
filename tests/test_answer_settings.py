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
