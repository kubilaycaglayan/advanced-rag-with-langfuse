"""English translation of a question asked in another language."""
import os
import unittest
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

    def test_setting(self):
        self.assertTrue(ResolvedPipelineConfig().query_translation)
        self.assertFalse(ResolvedPipelineConfig.from_mapping({"query_translation": False}).query_translation)
        with self.assertRaises(ValueError):
            ResolvedPipelineConfig.from_mapping({"query_translation": "no"})


if __name__ == "__main__":
    unittest.main()
