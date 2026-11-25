"""Name completion, streaming answers, and reasoning-answer fallback."""
import json
import os
import unittest
from contextlib import nullcontext
from pathlib import Path
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


class KeywordSearchChecks(unittest.TestCase):
    def setUp(self):
        pipeline._keyword_index.cache_clear()

    def tearDown(self):
        pipeline._keyword_index.cache_clear()


    def test_rare_exact_words_rank_first(self):
        texts = ["She thought: no compromises.", "He made a compromise.", "No time to lose, she said.", "The house was quiet."]
        client = MagicMock()
        client.scroll.return_value = ([MagicMock(id=f"p{i}", payload={"text": t}) for i, t in enumerate(texts)], None)
        with patch.object(pipeline, "qdrant_client", return_value=client):
            hits = pipeline._keyword_search('What is "no compromises"?', "c", 10)
        # Stop words ("what", "is") are ignored, a plural matches its singular, and passages sharing no word are not returned.
        self.assertEqual([row["id"] for row in hits], ["p0", "p1", "p2"])
        self.assertGreater(hits[0]["keyword_score"], hits[1]["keyword_score"])


class SceneSearchChecks(unittest.TestCase):
    def test_validation(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.scene_window, config.scene_stride, config.scene_search_hits), (6, 3, 10))
        from app import scenes
        self.assertEqual(scenes.summary_model(config), "gemma4:26b")
        self.assertFalse(config.scene_thinking)
        self.assertTrue(ResolvedPipelineConfig.from_mapping({"scene_thinking": True}).scene_thinking)
        with self.assertRaises(ValueError):
            ResolvedPipelineConfig.from_mapping({"scene_thinking": "yes"})
        # null: the generation model writes the summaries, as before the setting existed.
        self.assertEqual(scenes.summary_model(ResolvedPipelineConfig.from_mapping({"scene_summary_model": None})), "qwen3:8b")
        self.assertNotEqual(scenes.scene_collection("c", config), scenes.scene_collection("c", ResolvedPipelineConfig.from_mapping({"scene_summary_model": None})))
        for bad in ({"scene_window": 0}, {"scene_stride": 7}, {"scene_window": 21, "scene_stride": 3}, {"scene_search_hits": 0}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)


class MomentSceneChecks(unittest.TestCase):


    def _hits(self, replies, evidence=("p20",), present=("p20",)):
        # Windows of three passages, stride two, in one section: s0 = p0..p2, s1 = p2..p4, s2 = p4..p6. The search returns
        # them out of reading order; the model is shown them in reading order.
        scenes = [MagicMock(id=f"s{i}", payload={"members": [f"p{2 * i + j}" for j in range(3)], "summary": f"sum{i}"}) for i in range(3)]
        passage = lambda i: MagicMock(id=i, payload={"text": f"t{i}", "book": "B", "section": "x", "paragraph": int(i[1:]), "part": 1})
        client = MagicMock()
        client.query_points.return_value = MagicMock(points=[scenes[2], scenes[0], scenes[1]])
        client.scroll.side_effect = lambda **kw: ([s for s in scenes if set(s.payload["members"]) & set(kw["scroll_filter"].must[0].match.any)], None)
        client.retrieve.side_effect = lambda collection_name, ids, with_payload: [passage(i) for i in reversed(ids)]
        reranker = MagicMock()
        reranker.predict.side_effect = lambda pairs, show_progress_bar: [0.0] * len(pairs)
        embedder = MagicMock()
        embedder.encode.return_value = MagicMock(tolist=lambda: [0.0])
        prompts = []
        config = ResolvedPipelineConfig(name_completion=False)
        with patch.object(pipeline, "_embedder", return_value=embedder), patch.object(pipeline, "_reranker", return_value=reranker), \
                patch.object(pipeline, "_ollama", side_effect=lambda messages, *a, **k: prompts.append(messages[-1]["content"]) or replies.pop(0)):
            rows, moment = pipeline._moment_scene_hits("q", config, "c", client, [{"id": i} for i in evidence], set(present))
        return [row["id"] for row in rows], moment, prompts


    def test_chosen_window_and_the_window_that_continues_it_are_added_in_reading_order(self):
        ids, moment, prompts = self._hits(["MOMENT: X first met Y at home\nDETAIL: her shirt", "2"])
        self.assertEqual(moment, "X first met Y at home")
        self.assertLess(prompts[1].index("sum0"), prompts[1].index("sum1"))
        self.assertLess(prompts[1].index("sum1"), prompts[1].index("sum2"))
        self.assertEqual(ids, ["p2", "p3", "p4", "p5", "p6"])

    def test_nothing_is_added_without_a_moment_a_choice_or_new_evidence(self):
        self.assertEqual(self._hits(["MOMENT: none\nDETAIL: her mother"])[:2], ([], ""))
        self.assertEqual(self._hits(["MOMENT: X met Y", "none"])[0], [])
        self.assertEqual(self._hits(["MOMENT: X met Y", "7"])[0], [])
        # The evidence already holds a passage of the chosen span.
        self.assertEqual(self._hits(["MOMENT: X met Y", "1"], evidence=("p3",), present=("p3",))[0], [])
        # Passages already present elsewhere are not repeated.
        self.assertEqual(self._hits(["MOMENT: X met Y", "1"], present=("p20", "p1"))[0], ["p0", "p2", "p3", "p4"])




if __name__ == "__main__":
    unittest.main()


class SceneSummaryNameChecks(unittest.TestCase):
    def setUp(self):
        from app import scenes
        self.scenes = scenes
        books = (["and Mikael Blomkvist said hello. " * 25 + "Then he saw Blomkvist and Salander. " * 40
                  + "and Lisbeth Salander left. " * 25 + "and Wadensjöö came, and Armansky too. " * 5
                  + "Meanwhile it rained. meanwhile it rained. " * 10])
        self.lexicon = scenes.NameLexicon(books)

    def test_lexicon(self):
        self.assertTrue(self.lexicon.is_name("Blomkvist"))
        self.assertTrue(self.lexicon.is_name("Wästberg"))  # not in the books at all: invented
        self.assertFalse(self.lexicon.is_name("Meanwhile"))
        self.assertEqual((self.lexicon.partner["Mikael"], self.lexicon.partner["Lisbeth"]), ("Blomkvist", "Salander"))

    def test_names_written_as_the_excerpt_does(self):
        excerpt = "Blomkvist looked at Salander. Wadensjöö and Armansky waited."
        repair = lambda text: self.scenes.repair_summary(text, excerpt, self.lexicon)
        self.assertEqual(repair("Mikael Blomkvist meets Lisbeth."), ("Blomkvist meets Salander.", []))
        self.assertEqual(repair("Martin Blomkvist and Henrik Armansky talk."), ("Blomkvist and Armansky talk.", []))
        self.assertEqual(repair("Wadensjö worries."), ("Wadensjöö worries.", []))
        self.assertEqual(repair("In Chapter 5 of *The Girl with the Dragon Tattoo*, Blomkvist waits."), ("In the excerpt, Blomkvist waits.", []))
        # An invented person cannot be traced to the excerpt.
        self.assertEqual(repair("Elin Wästberg greets Salander.")[1], ["Elin", "Wästberg"])

    def test_untraced_summary_is_written_again_with_the_excerpts_names(self):
        points = [MagicMock(payload={"text": "Blomkvist looked at Salander.", "book": "b"})]
        with patch.object(self.scenes, "_summarise", return_value="Blomkvist sees Salander.") as summarise:
            summary, untraced = self.scenes.checked_summary(points, ResolvedPipelineConfig(), self.lexicon, "Elin Wästberg sees Salander.")
        self.assertEqual((summary, untraced), ("Blomkvist sees Salander.", []))
        self.assertEqual(summarise.call_args.args[2], ["Blomkvist", "Salander"])
