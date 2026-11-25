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

    def test_validation(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.keyword_hits, config.keyword_margin, config.keyword_max_hits), (30, 4.0, 5))
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"keyword_margin": None}).keyword_margin)
        for bad in ({"keyword_hits": -1}, {"keyword_hits": 201}, {"keyword_hits": True}, {"keyword_margin": -1}, {"keyword_margin": "x"},
                    {"keyword_margin": float("nan")}, {"keyword_margin": True}, {"keyword_max_hits": -1}, {"keyword_max_hits": 31}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def test_rare_share_validation(self):
        self.assertIsNone(ResolvedPipelineConfig().keyword_rare_share)
        self.assertEqual(ResolvedPipelineConfig.from_mapping({"keyword_rare_share": 0.01}).keyword_rare_share, 0.01)
        for bad in ({"keyword_rare_share": 0}, {"keyword_rare_share": 1.5}, {"keyword_rare_share": True}, {"keyword_rare_share": "x"}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def test_rare_question_words_leave_out_names_and_common_words(self):
        texts = ["Salander ran.", "Salander slept.", "Salander had a fake identity.", "The identity of Salander.", "She ran.", "He ran."]
        client = MagicMock()
        client.scroll.return_value = ([MagicMock(id=f"p{i}", payload={"text": t}) for i, t in enumerate(texts)], None)
        with patch.object(pipeline, "qdrant_client", return_value=client):
            # "salander" is a name, "ran" is in half the passages, "lost" is in none.
            self.assertEqual(pipeline._rare_question_words("Why ran Salander's fake identity lost?", "c", 0.4), {"fake", "identity"})
        self.assertTrue(pipeline._sentence_holds("She drove. The fake identity was lost.", {"fake", "identity"}))
        self.assertFalse(pipeline._sentence_holds("It was fake. Her identity was lost.", {"fake", "identity"}))

    def test_rare_exact_words_rank_first(self):
        texts = ["She thought: no compromises.", "He made a compromise.", "No time to lose, she said.", "The house was quiet."]
        client = MagicMock()
        client.scroll.return_value = ([MagicMock(id=f"p{i}", payload={"text": t}) for i, t in enumerate(texts)], None)
        with patch.object(pipeline, "qdrant_client", return_value=client):
            hits = pipeline._keyword_search('What is "no compromises"?', "c", 10)
        # Stop words ("what", "is") are ignored, a plural matches its singular, and passages sharing no word are not returned.
        self.assertEqual([row["id"] for row in hits], ["p0", "p1", "p2"])
        self.assertGreater(hits[0]["keyword_score"], hits[1]["keyword_score"])

    def test_admitted_passage_is_joined_with_the_one_before_it(self):
        payloads = [{"text": "Giannini asked for acquittal.", "book_file": "b", "section": "s", "paragraph": 14, "part": 1},
                    {"text": "No compromises.", "book_file": "b", "section": "s", "paragraph": 22, "part": 1},
                    {"text": "Elsewhere.", "book_file": "b", "section": "t", "paragraph": 1, "part": 1}]
        client = MagicMock()
        client.scroll.return_value = ([MagicMock(id=f"p{i}", payload=p) for i, p in enumerate(payloads)], None)
        pipeline._previous_passages.cache_clear()
        with patch.object(pipeline, "qdrant_client", return_value=client):
            joined = pipeline._with_previous_passage({"id": "p1", "text": "No compromises.", "paragraph": 22, "rerank_score": 1.9}, "c")
            # The first passage of a section has nothing before it.
            first = pipeline._with_previous_passage({"id": "p2", "text": "Elsewhere.", "paragraph": 1}, "c")
        pipeline._previous_passages.cache_clear()
        self.assertEqual((joined["text"], joined["paragraph"], joined["rerank_score"], joined["joined_previous"]),
                         ("Giannini asked for acquittal.\nNo compromises.", 14, 1.9, "p0"))
        self.assertEqual(first["text"], "Elsewhere.")


class LowConfidenceSettingChecks(unittest.TestCase):
    def test_defaults_and_validation(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.top_k, config.answer_thinking, config.low_confidence_score, config.low_confidence_top_k), (10, False, 2.0, 15))
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"low_confidence_score": None}).low_confidence_score)
        for bad in ({"low_confidence_score": "high"}, {"low_confidence_score": float("nan")}, {"low_confidence_top_k": 0}, {"low_confidence_top_k": 31}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)




class SceneSearchChecks(unittest.TestCase):
    def test_validation(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.scene_margin, config.scene_window, config.scene_stride, config.scene_search_hits), (1.0, 6, 3, 10))
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"scene_margin": None}).scene_margin)
        from app import scenes
        self.assertEqual(scenes.summary_model(config), "gemma4:26b")
        self.assertFalse(config.scene_thinking)
        self.assertTrue(ResolvedPipelineConfig.from_mapping({"scene_thinking": True}).scene_thinking)
        with self.assertRaises(ValueError):
            ResolvedPipelineConfig.from_mapping({"scene_thinking": "yes"})
        # null: the generation model writes the summaries, as before the setting existed.
        self.assertEqual(scenes.summary_model(ResolvedPipelineConfig.from_mapping({"scene_summary_model": None})), "qwen3:8b")
        self.assertNotEqual(scenes.scene_collection("c", config), scenes.scene_collection("c", ResolvedPipelineConfig.from_mapping({"scene_summary_model": None})))
        for bad in ({"scene_margin": -1}, {"scene_margin": "x"}, {"scene_margin": True}, {"scene_margin": float("nan")},
                    {"scene_window": 0}, {"scene_stride": 7}, {"scene_window": 21, "scene_stride": 3}, {"scene_search_hits": 0}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def _hits(self, scene_scores, evidence=("p1",), present=("p1",), **settings):
        # Scenes s0..s2 hold passages p0..p8 three at a time; s0 holds the evidence passage p1.
        scenes = [MagicMock(id=f"s{i}", payload={"members": [f"p{3 * i + j}" for j in range(3)], "summary": f"sum{i}"}) for i in range(3)]
        client = MagicMock()
        client.query_points.return_value = MagicMock(points=scenes)
        client.scroll.side_effect = lambda **kw: ([s for s in scenes if set(s.payload["members"]) & set(kw["scroll_filter"].must[0].match.any)], None)
        client.retrieve.side_effect = lambda collection_name, ids, with_payload: [MagicMock(id=i, payload={"text": f"t{i}"}) for i in reversed(ids)]
        reranker = MagicMock()
        reranker.predict.side_effect = lambda pairs, show_progress_bar: [scene_scores.get(text, 0.0) for _, text in pairs]
        embedder = MagicMock()
        embedder.encode.return_value = MagicMock(tolist=lambda: [0.0])
        config = ResolvedPipelineConfig(**{"scene_margin": 1.0} | settings)
        with patch.object(pipeline, "_embedder", return_value=embedder), patch.object(pipeline, "_reranker", return_value=reranker):
            rows = pipeline._scene_hits("q", config, "c", client, [{"id": i} for i in evidence], set(present))
        return [row["id"] for row in rows]

    def test_scene_admitted_only_when_it_beats_the_scenes_holding_the_evidence(self):
        # s1 beats s0 (the scene of the evidence) by more than the margin: its passages are added in reading order.
        self.assertEqual(self._hits({"sum0": 3.0, "sum1": 4.5, "sum2": 1.0}), ["p3", "p4", "p5"])
        # Not by more than the margin, or the evidence's own scene is the best: nothing is added.
        self.assertEqual(self._hits({"sum0": 3.6, "sum1": 4.5}), [])
        self.assertEqual(self._hits({"sum0": 5.0, "sum1": 4.5}), [])
        # A scene that is not a confident match is not added even if nothing covers the evidence.
        self.assertEqual(self._hits({"sum1": 1.5}, evidence=("p9",)), [])
        self.assertEqual(self._hits({"sum1": 2.5}, evidence=("p9",)), ["p3", "p4", "p5"])
        # Passages already in the evidence are not repeated.
        self.assertEqual(self._hits({"sum0": 3.0, "sum1": 4.5}, present=("p1", "p4")), ["p3", "p5"])


class MomentSceneChecks(unittest.TestCase):
    def test_setting_is_validated(self):
        self.assertTrue(ResolvedPipelineConfig().scene_moment)
        self.assertFalse(ResolvedPipelineConfig.from_mapping({"scene_moment": False}).scene_moment)
        for bad in ({"scene_moment": "yes"},):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

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
        config = ResolvedPipelineConfig(scene_moment=True, name_completion=False)
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


class SceneContextChecks(unittest.TestCase):
    def test_setting_is_validated(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.scene_context, config.scene_context_rank, config.scene_context_max_hits, config.scene_context_sentences), (True, 3, 2, 2))
        self.assertFalse(ResolvedPipelineConfig.from_mapping({"scene_context": False}).scene_context)
        for bad in ({"scene_context": "yes"}, {"scene_context_rank": 0},
                    {"scene_context_rank": True}, {"scene_context_max_hits": 0}, {"scene_context_max_hits": 11},
                    {"scene_context_sentences": 0}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def test_each_passage_takes_the_summary_of_the_window_it_sits_nearest_the_middle_of(self):
        from app import scenes
        contexts = scenes.passage_contexts([(["p0", "p1", "p2"], "s0"), (["p2", "p3", "p4"], "s1"), (["p4", "p5"], "s2")])
        self.assertEqual(contexts, {"p0": "s0", "p1": "s0", "p2": "s0", "p3": "s1", "p4": "s2", "p5": "s2"})

    def test_context_keeps_the_summary_sentences_nearest_the_passage_in_summary_order(self):
        import numpy as np
        from app import scenes
        axis = {"gun": 0, "bench": 1, "car": 2}
        encoder = MagicMock()
        encoder.encode.side_effect = lambda texts, **kw: np.array([[1.0 if word in text else 0.0 for word in axis] for text in texts])
        contexts = {"p": "He drives a car. She lies on a bench. He takes the gun."}
        self.assertEqual(scenes.focused_contexts(contexts, {"p": "the gun on the bench"}, 2, encoder), {"p": "She lies on a bench. He takes the gun."})
        self.assertEqual(scenes.focused_contexts(contexts, {"p": "the car"}, 1, encoder), {"p": "He drives a car."})

    def _hits(self, scores, present=("f0",), **settings):
        # Fused candidates f0, f1; the contextual search finds f1 (already fused), n0 and n1. Every row is reranked with its
        # summary in front ("ctx-<id>").
        candidates = [{"id": "f0", "text": "tf0", "rerank_score": 1.0}, {"id": "f1", "text": "tf1", "rerank_score": 0.5}]
        found = lambda i: MagicMock(id=i, payload={"text": f"t{i}", "context": f"ctx-{i}"})
        client = MagicMock()
        client.query_points.return_value = MagicMock(points=[found("f1"), found("n0"), found("n1")])
        client.retrieve.side_effect = lambda collection_name, ids, with_payload: [MagicMock(id=i, payload={"context": f"ctx-{i}"}) for i in ids]
        reranker = MagicMock()
        reranker.predict.side_effect = lambda pairs, show_progress_bar: [scores.get(text.split("\n")[0], 0.0) for _, text in pairs]
        config = ResolvedPipelineConfig(**{"scene_context": True} | settings)
        with patch.object(pipeline, "_reranker", return_value=reranker):
            rows = pipeline._context_hits("q", config, "c", client, [[0.0], [0.0]], ["q", "q"],
                                          candidates, set(present))
        return [row["id"] for row in rows]

    def test_passages_ranking_among_the_best_with_their_summary_are_added(self):
        # n0 ranks first with its summary in front and is a confident match.
        self.assertEqual(self._hits({"ctx-n0": 5.0, "ctx-f0": 4.0}), ["n0"])
        # A fused candidate outside the usual evidence can be added too; one in it is not repeated.
        self.assertEqual(self._hits({"ctx-f1": 5.0, "ctx-f0": 4.0}), ["f1"])
        self.assertEqual(self._hits({"ctx-f0": 5.0}), [])
        # Not among the best scene_context_rank, or not a confident match: nothing is added.
        self.assertEqual(self._hits({"ctx-n0": 3.0, "ctx-f0": 5.0, "ctx-f1": 4.0}, present=("f0", "f1"), scene_context_rank=2), [])
        self.assertEqual(self._hits({"ctx-n0": 1.5}), [])
        # At most scene_context_max_hits.
        self.assertEqual(self._hits({"ctx-n0": 5.0, "ctx-n1": 4.0}, scene_context_max_hits=1), ["n0"])


class ThinkingFallbackChecks(unittest.TestCase):
    def test_empty_reasoning_answer_retries_without_thinking(self):
        calls = []

        def post(url, json, timeout=None, **kwargs):
            calls.append(json["think"])
            response = MagicMock()
            response.json.return_value = {"message": {"content": "" if json["think"] else "Answer [E1]."}}
            return response

        with patch.object(pipeline.requests, "post", side_effect=post):
            self.assertEqual(pipeline._ollama([{"role": "user", "content": "q"}], "m", (10, 20), think=True), "Answer [E1].")
        self.assertEqual(calls, [True, True, False])

class StreamingChecks(unittest.TestCase):
    def test_streams_only_answer_content_and_records_usage(self):
        lines = [
            json.dumps({"message": {"thinking": "reasoning", "content": ""}, "done": False}),
            json.dumps({"message": {"content": "Hello "}, "done": False}),
            json.dumps({"message": {"content": "world"}, "done": True, "prompt_eval_count": 11, "eval_count": 2}),
        ]
        class Response:
            def raise_for_status(self): pass
            def iter_lines(self): return iter(lines)
            def __enter__(self): return self
            def __exit__(self, *exc): return False
        sent, updates, tokens = [], [], []
        with patch.object(pipeline.requests, "post", side_effect=lambda url, json, **kw: sent.append(json) or Response()), \
             patch.object(pipeline, "_observe", return_value=nullcontext(None)), \
             patch.object(pipeline, "_update", side_effect=lambda obs, **kw: updates.append(kw)):
            text = pipeline._ollama([{"role": "user", "content": "q"}], "m", (10,), on_token=tokens.append)
        self.assertEqual(text, "Hello world")
        self.assertEqual(tokens, ["Hello ", "world"])
        self.assertTrue(sent[0]["stream"])
        self.assertEqual(updates[-1]["output"], "Hello world")
        self.assertEqual(updates[-1]["usage_details"], {"input": 11, "output": 2})
        self.assertEqual(updates[-1]["metadata"], {"thinking": "reasoning"})

    def test_streamed_content_matches_non_streamed_stripping(self):
        lines = [json.dumps({"message": {"content": piece}, "done": False}) for piece in ("  ", " Hello ", "world ")]
        lines.append(json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 1, "eval_count": 2}))
        class Response:
            def raise_for_status(self): pass
            def iter_lines(self): return iter(lines)
            def __enter__(self): return self
            def __exit__(self, *exc): return False
        tokens = []
        with patch.object(pipeline.requests, "post", return_value=Response()), \
             patch.object(pipeline, "_observe", return_value=nullcontext(None)), \
             patch.object(pipeline, "_update"):
            text = pipeline._ollama([{"role": "user", "content": "q"}], "m", (10,), on_token=tokens.append)
        self.assertEqual(text, "Hello world")
        self.assertEqual("".join(tokens).strip(), text)


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
