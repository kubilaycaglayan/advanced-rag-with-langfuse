"""English translation of a question asked in another language."""
import os
import unittest
import unittest.mock
from unittest.mock import patch

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app import pipeline
from app.resolved_config import ResolvedPipelineConfig


class QueryTranslationChecks(unittest.TestCase):
    def _translate(self, reply, question="Lisbeth Salander'ın kız kardeşinin adı ne?"):
        with patch.object(pipeline, "_ollama", return_value=reply):
            return pipeline._translate(question, ResolvedPipelineConfig())

    def test_english_question_is_not_translated(self):
        # Even when the model rewords an English question, the question is kept as asked.
        self.assertIsNone(self._translate("LANGUAGE: English\nENGLISH: Who is Lisbeth's sister?", "Who is Lisbeth Salander's sister?"))
        self.assertIsNone(self._translate("LANGUAGE: Turkish\nENGLISH: Who is Lisbeth Salander's sister?", "Who is Lisbeth Salander's sister?"))
        self.assertIsNone(self._translate("no idea"))

    def test_other_language_is_translated(self):
        self.assertEqual(self._translate("LANGUAGE: Turkish\nENGLISH: What is the name of Lisbeth Salander's sister?\n"),
                         "What is the name of Lisbeth Salander's sister?")

    def test_plainly_english_question_skips_the_translation_request(self):
        books = ["Salander asked who killed the man in the kitchen. " * 3 + "Lisbeth Salander and Zalachenko met. " * 3]
        with patch.object(pipeline, "_word_counts", return_value=self._counts(books)):
            # Names do not count, and an English word the books do not use lowers the share but keeps it English.
            self.assertEqual(pipeline._english_share("Who killed Lisbeth Salander in the kitchen?", "c"), 1.0)
            self.assertGreaterEqual(pipeline._english_share("Who killed the man in the doorway?", "c"), 0.6)
            self.assertLess(pipeline._english_share("Wer hat Lisbeth Salander getötet?", "c"), 0.6)
            self.assertLess(pipeline._english_share("Vem dödade Zalachenko?", "c"), 0.6)

    def _counts(self, texts):
        pipeline._word_counts.cache_clear()
        client = unittest.mock.MagicMock()
        client.scroll.return_value = ([unittest.mock.MagicMock(payload={"text": t}) for t in texts], None)
        with patch.object(pipeline, "qdrant_client", return_value=client):
            counts = pipeline._word_counts("c")
        pipeline._word_counts.cache_clear()
        return counts

    def test_setting(self):
        self.assertEqual(ResolvedPipelineConfig().english_word_share, 0.6)
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"english_word_share": None}).english_word_share)
        for bad in ({"english_word_share": 1.5}, {"english_word_share": True}, {"english_word_share": "x"}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)
        self.assertTrue(ResolvedPipelineConfig().query_translation)
        self.assertFalse(ResolvedPipelineConfig.from_mapping({"query_translation": False}).query_translation)
        with self.assertRaises(ValueError):
            ResolvedPipelineConfig.from_mapping({"query_translation": "no"})


if __name__ == "__main__":
    unittest.main()
