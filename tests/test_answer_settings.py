"""Name completion and reasoning-answer fallback."""
import os
import unittest
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


class WideCandidateChecks(unittest.TestCase):
    def test_validation(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.wide_candidate_count, config.wide_trigger_score), (100, 3.5))
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"wide_trigger_score": None}).wide_trigger_score)
        self.assertEqual((config.wide_max_hits, config.wide_override_margin), (3, 2.0))
        self.assertIsNone(ResolvedPipelineConfig.from_mapping({"wide_override_margin": None}).wide_override_margin)
        for bad in ({"wide_candidate_count": -1}, {"wide_candidate_count": 201}, {"wide_candidate_count": True}, {"wide_trigger_score": "x"},
                    {"wide_max_hits": -1}, {"wide_max_hits": 31}, {"wide_override_margin": -1}, {"wide_override_margin": "x"},
                    {"wide_override_margin": float("nan")}, {"wide_override_margin": True}):
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
        config = ResolvedPipelineConfig(**{"retrieval_mode": "query_expansion", "candidate_count": 3, "top_k": 3, "low_confidence_top_k": 3, "wide_candidate_count": 6,
                                            "scene_margin": None, "query_translation": False, "keyword_hits": 0} | settings)
        with patch.object(pipeline, "qdrant_client", return_value=client), patch.object(pipeline, "_embedder", return_value=embedder), \
                patch.object(pipeline, "_reranker", return_value=reranker), patch.object(pipeline, "_transform", return_value=(None, ["alt"], None)), \
                patch.object(pipeline, "_complete_names", return_value="q named" if named_scores else "q"), \
                patch.object(pipeline, "_ollama", return_value="Answer [E1].") as ollama:
            result = pipeline.run_pipeline("q", config, collection="c")
        self.sent = [call.args[0] for call in ollama.call_args_list]
        limits = [call.kwargs["limit"] for call in client.query_points.call_args_list]
        # The completed-name search, when there is one, is the last search and looks deeper.
        named_search = bool(named_scores) and config.name_completion
        self.assertEqual(limits, [max(3, config.wide_candidate_count)] * 2 + ([max(3, config.wide_candidate_count, config.name_completion_hits)] if named_search else []))
        return [row["id"] for row in result["reranked"]], result["low_confidence"]

    def test_wide_passage_added_in_front_only_when_it_beats_fused_candidates(self):
        base = {"t0": 1.0, "t1": 3.0, "t2": 0.5, "t3": 4.0, "t4": 2.9, "t5": -1.0}
        # p3 beats every fused candidate and is a confident match: added before the unchanged evidence.
        self.assertEqual(self._run(base), (["p3", "p1", "p0", "p2"], False))
        # A strong fused match (>= wide_trigger_score) keeps the evidence unchanged.
        self.assertEqual(self._run(base | {"t1": 3.6}), (["p1", "p0", "p2"], False))
        self.assertEqual(self._run(base | {"t1": 3.6}, wide_trigger_score=None), (["p3", "p1", "p0", "p2"], False))
        # Unless a wider passage beats it by more than wide_override_margin.
        self.assertEqual(self._run(base | {"t1": 3.6, "t3": 5.7}), (["p3", "p1", "p0", "p2"], False))
        self.assertEqual(self._run(base | {"t1": 3.6, "t3": 5.5}), (["p1", "p0", "p2"], False))
        self.assertEqual(self._run(base | {"t1": 3.6, "t3": 5.7}, wide_override_margin=None), (["p1", "p0", "p2"], False))
        # Beating the fused candidates is not enough below the low-confidence threshold.
        self.assertEqual(self._run(base | {"t1": 1.5, "t3": 1.9, "t4": 1.8}), (["p1", "p0", "p2"], True))
        # A wider pool no larger than candidate_count adds nothing.
        self.assertEqual(self._run(base, wide_candidate_count=3)[0], ["p1", "p0", "p2"])
        # At most wide_max_hits passages are admitted, best first.
        self.assertEqual(self._run(base | {"t4": 3.2}, wide_max_hits=1)[0], ["p3", "p1", "p0", "p2"])

    def test_keyword_passages_added_in_front_only_when_one_beats_fused_candidates_by_the_margin(self):
        base = {"t0": -6.0, "t1": -5.0, "t2": -7.0, "t3": -8.0, "t4": -8.0, "t5": -8.0, "k0": -0.5, "k1": -2.0, "k2": -5.5}
        keyword = [{"id": "k0", "text": "k0"}, {"id": "k1", "text": "k1"}, {"id": "k2", "text": "k2"}, {"id": "p1", "text": "t1"}]
        with patch.object(pipeline, "_keyword_search", return_value=keyword) as search, \
                patch.object(pipeline, "_previous_passages", return_value={}):
            # k0 beats the best fused candidate (-5.0) by more than 4.0, so the keyword hits that beat it (k0, k1) go in
            # front, even on the low-confidence path; k2 does not beat it; p1 is already a fused candidate.
            self.assertEqual(self._run(base, keyword_hits=30), (["k0", "k1", "p1", "p0", "p2"], True))
            self.assertEqual(search.call_args.args, ("q", "c", 30))
            self.assertEqual(self._run(base, keyword_hits=30, keyword_max_hits=1)[0], ["k0", "p1", "p0", "p2"])
            # No keyword hit clears the margin: nothing is added.
            self.assertEqual(self._run(base | {"k0": -1.5}, keyword_hits=30)[0], ["p1", "p0", "p2"])
            # Admitted passages are given in reading order, not score order.
            keyword[0]["paragraph"], keyword[1]["paragraph"] = 9, 2
            self.assertEqual(self._run(base, keyword_hits=30)[0], ["k1", "k0", "p1", "p0", "p2"])
            # Off by default, and with no margin.
            self.assertEqual(self._run(base)[0], ["p1", "p0", "p2"])
            self.assertEqual(self._run(base, keyword_hits=30, keyword_margin=None)[0], ["p1", "p0", "p2"])

    def test_keyword_passages_holding_every_rare_question_word_in_one_sentence_are_added_at_any_score(self):
        base = {"t0": 1.0, "t1": 3.0, "t2": 0.5, "t3": -8.0, "t4": -8.0, "t5": -8.0, "a fake. identity": -9.0, "the fake identity": -7.0, "fake": 2.0}
        keyword = [{"id": "k0", "text": "a fake. identity"}, {"id": "k1", "text": "the fake identity"}, {"id": "k2", "text": "fake"}]
        with patch.object(pipeline, "_keyword_search", return_value=keyword), patch.object(pipeline, "_previous_passages", return_value={"k1": {"id": "k9", "text": "before"}}), \
                patch.object(pipeline, "_rare_question_words", return_value={"fake", "identity"}) as rare:
            # Only k1 holds both words in one sentence; it is added in front, not joined with the passage before it.
            self.assertEqual(self._run(base, keyword_hits=30, keyword_rare_share=0.01)[0], ["k1", "p1", "p0", "p2"])
            self.assertEqual(rare.call_args.args, ("q", "c", 0.01))
            # Off by default; one rare word is not enough.
            self.assertEqual(self._run(base, keyword_hits=30)[0], ["p1", "p0", "p2"])
            rare.return_value = {"fake"}
            self.assertEqual(self._run(base, keyword_hits=30, keyword_rare_share=0.01)[0], ["p1", "p0", "p2"])

    def test_scene_context_passages_go_after_the_usual_evidence_and_before_the_scene(self):
        base = {"t0": 1.0, "t1": 3.0, "t2": 2.5, "t3": -8.0, "t4": -8.0, "t5": -8.0}
        context = [{"id": "c0", "text": "c0", "rerank_score": 5.0, "scene_context_hit": True}]
        scene = [{"id": i, "text": i, "scene_summary": "s", "scene_score": 3.0} for i in ("c0", "s0")]
        with patch.object(pipeline, "_context_hits", return_value=context) as hits, \
                patch.object(pipeline, "_scene_hits", return_value=scene) as scenes:
            self.assertEqual(self._run(base, scene_context=True, scene_margin=1.0, entity_names=False)[0], ["p1", "p2", "p0", "c0", "s0"])
            # The scene path sees the usual evidence only; the context path does not repeat it.
            self.assertEqual([row["id"] for row in scenes.call_args.args[4]], ["p1", "p2", "p0"])
            self.assertEqual(hits.call_args.args[6], {"p1", "p2", "p0"})
            # Off when switched off, or without the scene index.
            hits.reset_mock()
            self.assertEqual(self._run(base, scene_context=False, scene_margin=1.0, entity_names=False)[0], ["p1", "p2", "p0", "c0", "s0"])
            self.assertEqual(self._run(base, scene_margin=None, entity_names=False)[0], ["p1", "p2", "p0"])
            hits.assert_not_called()

    def test_entity_names_add_the_other_names_of_the_person_the_question_names(self):
        import json, tempfile
        edge = lambda name, relation, types, count, members: {"from": name.casefold(), "to": "lisbeth salander", "relation": relation, "count": count,
                                                             "types": types, "text": f"{name} — {relation} Salander: x", "members": members, "names": [name]}
        cards = {"alias": {"salander": "lisbeth salander"}, "cards": [{"key": "lisbeth salander", "mentions": 300}],
                 "edges": [edge("Irene Nesser", "false identity used by", ["false identity"], 2, ["n1"]),
                           edge("Magnus", "false identity used by", ["false identity"], 1, ["n1"]),
                           edge("Plague", "alias of", ["online handle"], 2, ["w1"]), edge("Plague", "friend of", ["person"], 1, ["w1"]),
                           edge("Wasp", "online name used by", ["online handle"], 3, ["w1"]),
                           edge("Lisbeth", "first name of", ["nickname"], 5, ["l1"]),
                           edge("leather jacket", "worn by", ["clothing"], 9, ["j1"])]}
        texts = {"n1": "under the name of Irene Nesser", "w1": "known online only as Wasp", "l1": "Lisbeth said", "j1": "a leather jacket"}
        client = MagicMock()
        client.retrieve.side_effect = lambda collection, ids, with_payload: [MagicMock(id=i, payload={"text": texts[i]}) for i in ids]
        scores = {"Irene Nesser — false identity used by Salander: x": 6.0, "Wasp — online name used by Salander: x": 0.5}
        reranker = MagicMock()
        reranker.predict.side_effect = lambda pairs, show_progress_bar: [scores.get(text, -3.0) for _, text in pairs]
        evidence = [{"id": "e1", "text": "unrelated"}]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(cards, handle); handle.flush()
            pipeline._entity_cards.cache_clear()
            with patch.object(pipeline, "entity_cards_path", return_value=Path(handle.name)), patch.object(pipeline, "_reranker", return_value=reranker):
                hits = lambda question, **settings: [row["entity"] for row in pipeline._entity_name_hits(
                    question, ResolvedPipelineConfig(**settings), "c", client, evidence)]
                # The best match leads, then the most often stated; the person's own name and other links are left out.
                self.assertEqual(hits("What is Salander's fake identity?", entity_names=True), ["irene nesser", "wasp"])
                self.assertEqual(hits("What is Salander's fake identity?", entity_names=False), [])
                # Evidence that already names the best match is left as it is.
                evidence.append({"id": "e2", "text": "She was Irene Nesser that day."})
                self.assertEqual(hits("What is Salander's fake identity?", entity_names=True), [])
                evidence.pop()
                # No confident match, or the best match is not another name: nothing is added.
                scores["Irene Nesser — false identity used by Salander: x"] = 1.0
                self.assertEqual(hits("What is Salander's fake identity?", entity_names=True), [])
                scores["leather jacket — worn by Salander: x"] = 7.0
                self.assertEqual(hits("What did Salander wear?", entity_names=True), [])
            pipeline._entity_cards.cache_clear()

    def test_entity_matrix_settings(self):
        config = ResolvedPipelineConfig()
        self.assertEqual((config.entity_matrix, config.entity_matrix_similarity, config.entity_matrix_max_hits), (True, 0.75, 8))
        for bad in ({"entity_matrix": 1}, {"entity_matrix_similarity": 0}, {"entity_matrix_similarity": 1.5}, {"entity_matrix_similarity": True},
                    {"entity_matrix_max_hits": 0}, {"entity_matrix_max_hits": 21}):
            with self.assertRaises(ValueError):
                ResolvedPipelineConfig.from_mapping(bad)

    def test_entity_matrix_finds_cells_from_any_end(self):
        import json, tempfile
        import numpy as np
        edge = lambda name, relation, kind, owner, count, member: {"from": name.casefold(), "to": owner, "relation": relation, "count": count, "types": [kind],
                                                                   "text": f"{name} — {relation} {owner.title()}: x", "members": [member], "names": [name]}
        card = lambda key, facts, mentions=10: {"key": key, "text": key, "members": [], "mentions": mentions, "facts": facts, "types": ["person"]}
        data = {"alias": {}, "cards": [card("jan bublanski", ["Jan Bublanski is a criminal inspector."], 50), card("bublanski", [], 5),
                                       card("erika berger", ["Erika Berger is an editor."], 40), card("officer bubble", []), card("ricky", []),
                                       card("curt", []), card("curt andersson", ["Curt Andersson is with the police."], 12), card("volvo", []), card("andersson", []),
                                       card("dragan armansky", ["Dragan Armansky runs Milton Security."], 30)],
                "edges": [edge("Officer Bubble", "nickname of", "nickname", "bublanski", 4, "b1"), edge("Ricky", "nickname of", "nickname", "erika berger", 9, "r1"),
                          edge("Curt", "nickname of", "nickname", "curt andersson", 3, "c1"), edge("Volvo", "owned by", "vehicle", "erika berger", 1, "v1"),
                          edge("Andersson", "nickname of", "nickname", "jan bublanski", 2, "a1"),
                          edge("Dragan Armansky", "nickname of", "nickname", "jan bublanski", 1, "d1")]}
        texts = {"b1": "Officer Bubble came in", "r1": "Ricky, Malm said", "c1": "Curt nodded", "v1": "her Volvo", "a1": "Andersson said", "d1": "Dragan Armansky said"}
        # One dimension per meaning: "car" is close to "vehicle", "nicknames" to "nickname".
        meanings = [("nickname",), ("vehicle", "car"), ("police", "inspector")]
        embedder = MagicMock()
        embedder.encode.side_effect = lambda texts, **_: np.array([[1.0 if any(word in text.lower() for word in words) else 0.0 for words in meanings] + [0.1]
                                                                   for text in texts])
        client = MagicMock()
        client.retrieve.side_effect = lambda collection, ids, with_payload: [MagicMock(id=i, payload={"text": texts[i]}) for i in ids]
        reranker = MagicMock()
        # Facts mentioning an inspector or the police match "police officers"; cells match questions naming their owner.
        reranker.predict.side_effect = lambda pairs, **_: [4.0 if ("police" in query and ("inspector" in text or "police" in text))
                                                           or ("Berger" in query and "Berger" in text) else -5.0 for query, text in pairs]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(data, handle); handle.flush()
            pipeline._entity_cards.cache_clear(); pipeline._entity_columns.cache_clear()
            with patch.object(pipeline, "entity_cards_path", return_value=Path(handle.name)), patch.object(pipeline, "_reranker", return_value=reranker), \
                    patch.object(pipeline, "_embedder", return_value=embedder):
                hits = lambda question, evidence=(): [row["entity"] for row in pipeline._entity_matrix_hits(
                    question, ResolvedPipelineConfig(entity_matrix=True), "c", client, list(evidence))]
                # The whole column, most often stated first; "Curt" is part of Curt Andersson's own name, and "Andersson" of
                # another person's (Curt Andersson), so neither is a nickname; nor is one window's claim about a person
                # the cards mention 30 times (Dragan Armansky).
                self.assertEqual(hits("What are the nicknames used in the book?"), ["ricky", "officer bubble"])
                # Left-over words ("police officers") pick the cells whose other end's facts match them.
                self.assertEqual(hits("Are there any police officers with nicknames?"), ["officer bubble"])
                # A named entity restricts the cells to it.
                self.assertEqual(hits("What car does Berger drive?"), ["volvo"])
                self.assertEqual(hits("What car does Berger drive?", [{"id": "e", "text": "She took the Volvo."}]), [])
                # No column, or evidence that already names the best cell: nothing.
                self.assertEqual(hits("Who is Berger?"), [])
                self.assertEqual(hits("What are the nicknames used in the book?", [{"id": "e", "text": "Malm  called her RICKY"}]), [])
            pipeline._entity_cards.cache_clear(); pipeline._entity_columns.cache_clear()

    def test_entity_cards_join_name_variants_and_link_other_names_to_the_person(self):
        from app.entities import merge_entities
        mention = lambda name, kind, owner=None, relation=None: {"name": name, "type": kind, "of": owner, "relation": relation, "fact": f"{name}."}
        windows = [{"members": ["a"], "book": "B", "entities": [mention("Lisbeth Salander", "person"), mention("Irene Nesser", "false identity", "Lisbeth Salander", "false identity used by")]},
                   {"members": ["b"], "book": "B", "entities": [mention("Salander", "person"), mention("Wasp", "online handle", "Salander", "online name used by"),
                                                                mention("Wasp Enterprises", "company", "Salander", "owned by"), mention("the woman", "person"), None]}]
        cards = merge_entities(windows)
        # "Salander" is a one-word name of Lisbeth Salander; Wasp stays apart from Wasp Enterprises; unnamed people are dropped.
        self.assertEqual(cards["alias"], {"salander": "lisbeth salander"})
        self.assertEqual({card["key"] for card in cards["cards"]}, {"lisbeth salander", "irene nesser", "wasp", "wasp enterprises"})
        edges = {edge["from"]: edge for edge in cards["edges"]}
        self.assertEqual({edge["to"] for edge in edges.values()}, {"lisbeth salander"})
        self.assertEqual((edges["wasp"]["text"], edges["wasp"]["types"], edges["wasp"]["members"]),
                         ("Wasp — online name used by Lisbeth Salander: Wasp.", ["online handle"], ["b"]))

    def test_completed_name_scores_the_wider_pool(self):
        base = {"t0": 1.0, "t1": 1.5, "t2": 0.5, "t3": -1.0, "t4": -1.0, "t5": -1.0, "t6": -5.0, "t7": -5.0}
        named = {"t0": 2.0, "t1": 4.0, "t2": 1.0, "t3": 3.0, "t4": 0.0, "t5": 0.0, "t6": 6.0, "t7": 3.9}
        # p6 is found only by the completed wording and beats every fused candidate under it; p3 and p7 do not
        # beat the best fused candidate under the completed wording (4.0). The fused evidence is unchanged.
        self.assertEqual(self._run(base, named), (["p6", "p1", "p0", "p2"], True))
        self.assertEqual(self._run(base, named, name_completion=False), (["p1", "p0", "p2"], True))

    def test_answer_model_sees_completed_question_only_for_completed_name_evidence(self):
        base = {"t0": 1.0, "t1": 1.5, "t2": 0.5, "t3": -1.0, "t4": -1.0, "t5": -1.0, "t6": -5.0, "t7": -5.0}
        named = {"t0": 2.0, "t1": 4.0, "t2": 1.0, "t3": 3.0, "t4": 0.0, "t5": 0.0, "t6": 6.0, "t7": 3.9}
        self._run(base, named)
        self.assertIn("Question: q named\n", self.sent[-1][-1]["content"])
        # The completed wording admits nothing: the answer model sees the question as asked.
        self._run(base, named | {"t6": 3.0})
        self.assertIn("Question: q\n", self.sent[-1][-1]["content"])

    def test_answer_model_sees_completed_question_for_passages_admitted_over_a_strong_match(self):
        base = {"t0": 1.0, "t1": 4.0, "t2": 0.5, "t3": -1.0, "t4": -1.0, "t5": -1.0, "t6": -5.0, "t7": -5.0}
        named = {"t0": 1.0, "t1": 3.0, "t2": 0.0, "t3": 7.0, "t4": 0.0, "t5": 0.0, "t6": -5.0, "t7": -5.0}
        # p3 is in the wider pool (not only the completed search) and clears the strong fused match by the margin.
        self.assertEqual(self._run(base, named), (["p3", "p1", "p0", "p2"], False))
        self.assertIn("Question: q named\n", self.sent[-1][-1]["content"])
        self.assertEqual(self._run(base, named | {"t3": 5.5}), (["p1", "p0", "p2"], False))
        self.assertIn("Question: q\n", self.sent[-1][-1]["content"])


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
            rows = pipeline._context_hits("q", config, "c", client, [[0.0], [0.0]], candidates, set(present))
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
