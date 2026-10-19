"""Agent tool protocol: tool parsing, citation mapping, answer guards and context compaction."""
import json
import os
import unittest
from unittest.mock import patch

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from collections import Counter

from app.agent import (AgentSettings, AgentState, _bare_name, _book_short, _candidate_others, _compact, _connection_pairs,
                       _covered_stages, _event_verb, _final, _finish, _int, _looks_like_abstention, _name_score,
                       _normalize_question, _parse_text_tool, _rank_facts, _relation_role, _resolve_id, _scene_member_rows,
                       _scene_payload, _speech_excerpt, _synthesis_rows, _tool_read_scene, _tool_scene_moment, _tool_specs,
                       _tool_submit_answer, _true_account_queries, _true_scene_rank, _is_moment_question, _moment_core,
                       _WHAT_HAPPENED, run_agent)
from app.resolved_config import ResolvedPipelineConfig


def state(**settings):
    values = {"min_tool_calls": 0, **settings}
    return AgentState(question="Who gave Salander the cigarette case?", collection="test", config=ResolvedPipelineConfig(),
                      settings=AgentSettings(**values), started=0.0)


class TextToolParsing(unittest.TestCase):
    def test_reads_a_printed_tool_call(self):
        self.assertEqual(_parse_text_tool('{"tool": "semantic_search", "arguments": {"query": "Salander"}}'),
                         ("semantic_search", {"query": "Salander"}))

    def test_reads_a_fenced_tool_call(self):
        content = 'thinking...\n```json\n{"tool": "keyword_search", "args": {"query": "Mimmi"}}\n```'
        self.assertEqual(_parse_text_tool(content), ("keyword_search", {"query": "Mimmi"}))

    def test_reads_a_name_and_arguments_object(self):
        self.assertEqual(_parse_text_tool('{"name": "read_passage", "arguments": {"id": "ab12cd34"}}'),
                         ("read_passage", {"id": "ab12cd34"}))

    def test_a_prose_answer_is_not_a_tool_call(self):
        self.assertIsNone(_parse_text_tool("Salander received the case from Mimmi Wu."))
        self.assertIsNone(_parse_text_tool('{"answer": "Mimmi Wu"}'))
        self.assertIsNone(_parse_text_tool('{"tool": "semantic_search", "arguments": broken}'))


class SubmitAnswer(unittest.TestCase):
    def test_cites_passages_it_collected(self):
        agent = state()
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "Mimmi Wu gave it to her."}}
        agent.order = ["a1b2c3d4"]
        payload, stop = _tool_submit_answer(agent, {"answer": "Mimmi Wu gave it to her [a1b2c3d4].",
                                                    "passage_ids": ["a1b2c3d4"]})
        self.assertTrue(stop)
        self.assertEqual(payload["answer"], "Mimmi Wu gave it to her [E1].")
        self.assertEqual(payload["passage_ids"], ["a1b2c3d4"])

    def test_rejects_an_id_it_never_returned(self):
        agent = state()
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "text"}}
        agent.order = ["a1b2c3d4"]
        payload, stop = _tool_submit_answer(agent, {"answer": "x", "passage_ids": ["deadbeef"]})
        self.assertFalse(stop)
        self.assertIn("unknown passage ids", payload["error"])

    def test_refuses_to_answer_without_evidence(self):
        payload, stop = _tool_submit_answer(state(), {"answer": "Mimmi Wu."})
        self.assertFalse(stop)
        self.assertIn("no evidence yet", payload["error"])

    def test_refuses_to_answer_before_investigating(self):
        agent = state(min_tool_calls=3)
        agent.tool_calls = 1
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "text"}}
        agent.order = ["a1b2c3d4"]
        payload, stop = _tool_submit_answer(agent, {"answer": "x [a1b2c3d4]", "passage_ids": ["a1b2c3d4"]})
        self.assertFalse(stop)
        self.assertIn("investigate more", payload["error"])

    def test_accepts_ids_written_with_brackets_or_commas(self):
        agent = state()
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "text"}}
        agent.order = ["a1b2c3d4"]
        payload, stop = _tool_submit_answer(agent, {"answer": "x [a1b2c3d4]", "passage_ids": "[a1b2c3d4,"})
        self.assertTrue(stop)
        self.assertEqual(payload["passage_ids"], ["a1b2c3d4"])


class FinalAnswer(unittest.TestCase):
    def test_drops_a_standalone_trailing_citation_line(self):
        agent = state()
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "one"},
                          "deadbeef": {"id": "deadbeef-0000-0000-0000-000000000000", "text": "two"}}
        result = _final(agent, "She said it.\n\n[E1] [E2]", ["a1b2c3d4", "deadbeef"], stopped="submit")
        self.assertEqual(result["answer"], "She said it.")

    def test_labels_the_evidence_in_the_order_the_agent_used_it(self):
        agent = state()
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "one"},
                          "deadbeef": {"id": "deadbeef-0000-0000-0000-000000000000", "text": "two"}}
        agent.trace = [{"tool": "semantic_search"}]
        agent.turns = 2
        result = _final(agent, "first [a1b2c3d4], then [deadbeef].", ["a1b2c3d4", "deadbeef"], stopped="submit")
        self.assertEqual(result["answer"], "first [E1], then [E2].")
        self.assertEqual(result["citations"], ["E1", "E2"])
        self.assertEqual([row["agent_label"] for row in result["evidence"]], ["E1", "E2"])


class ContextCompaction(unittest.TestCase):
    def test_compacts_older_results_and_keeps_the_ids(self):
        messages = [{"role": "user", "content": "question"}]
        for index in range(10):
            messages.append({"role": "tool", "content": json.dumps({"id": f"{index:08x}", "text": "x" * 4000})})
        _compact(messages, keep=3, budget=4000)
        self.assertIn("compacted", messages[1]["content"])
        for position, message in enumerate(messages[1:-3]):
            body = json.loads(message["content"])
            self.assertTrue(body["compacted"])
            self.assertEqual(body["ids"], [f"{position:08x}"])
        self.assertNotIn("compacted", messages[-3]["content"])


class Connections(unittest.TestCase):
    data = {
        "cards": [
            {"key": "mikael blomkvist", "mentions": 218, "facts": [
                "Lisbeth Salander wrote a report about Mikael Blomkvist.",
                "Mikael Blomkvist asked about Lisbeth Salander."]},
            {"key": "lisbeth salander", "mentions": 770, "facts": [
                "Lisbeth Salander wrote a report about Mikael Blomkvist."]},
        ],
        "edges": [
            {"from": "lisbeth salander", "to": "mikael blomkvist", "relation": "knows",
             "text": "Lisbeth Salander knows Mikael Blomkvist.", "members": ["a1b2c3d4"]},
            {"from": "clinic", "to": "lisbeth salander", "relation": "place",
             "text": "Salander was at the clinic.", "members": ["deadbeef"]},
        ],
        "alias": {},
    }

    def test_finds_the_fact_that_names_both_people(self):
        facts, _ = _connection_pairs(self.data, "mikael blomkvist", "lisbeth salander")
        self.assertEqual(facts[0]["fact"], "Lisbeth Salander wrote a report about Mikael Blomkvist.")
        self.assertEqual(facts[0]["score"], 8)  # both names, plus wrote and report

    def test_keeps_direct_edges_and_drops_ones_that_only_touch_a_person(self):
        _, edges = _connection_pairs(self.data, "mikael blomkvist", "lisbeth salander")
        self.assertEqual([edge["relation"] for edge in edges], ["knows"])

    def test_full_name_scores_higher_than_one_word(self):
        self.assertEqual(_name_score("Lisbeth Salander wrote a report.", "lisbeth salander"), 2)
        self.assertEqual(_name_score("Salander wrote a report.", "lisbeth salander"), 1)
        self.assertEqual(_name_score("Mimmi wrote a report.", "lisbeth salander"), 0)

    def test_ranks_facts_for_what_is_asked(self):
        facts = ["Blomkvist's apartment is on Bellmansgatan.", "Salander wrote a report about Blomkvist.", "Mimmi gave her a case."]
        self.assertIn("report", _rank_facts(facts, "report")[0])


class QuestionNormalization(unittest.TestCase):
    def test_replaces_a_misspelled_name_with_the_books_full_name(self):
        agent = state()
        agent.question = "How did Mikhail first know about Salander?"
        with patch("app.agent._name_pairs", return_value=({"Mikael": ("Mikael Blomkvist", 87, 367)},
                                                          Counter({"Mikael": 367, "Salander": 770}))):
            normalized, notes = _normalize_question(agent)
        self.assertEqual(normalized, "How did Mikael Blomkvist first know about Salander?")
        self.assertEqual(notes, [{"from": "Mikhail", "to": "Mikael Blomkvist"}])

    def test_leaves_names_the_books_use(self):
        agent = state()
        agent.question = "What did Salander do?"
        with patch("app.agent._name_pairs", return_value=({}, Counter({"Salander": 770}))):
            normalized, notes = _normalize_question(agent)
        self.assertEqual(normalized, "What did Salander do?")
        self.assertEqual(notes, [])


class AbstentionRecovery(unittest.TestCase):
    def test_recognises_the_loops_abstention_wording(self):
        self.assertTrue(_looks_like_abstention("The provided passages do not contain information about that."))
        self.assertTrue(_looks_like_abstention("Information not found in the sources."))
        self.assertFalse(_looks_like_abstention("Mikael learned about her from the report."))

    def test_answers_from_the_evidence_instead_of_abstaining(self):
        agent = state()
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "the report"}}
        agent.order = ["a1b2c3d4"]
        with patch("app.agent._synthesize", return_value=("He learned about her from the report [a1b2c3d4].", ["a1b2c3d4"])):
            result = _finish(agent, "The provided passages do not contain information.", [], stopped="content")
        self.assertEqual(result["answer"], "He learned about her from the report [E1].")
        self.assertEqual(result["stopped"], "content+synthesis")


class SceneReading(unittest.TestCase):
    rows = [
        {"id": "aaaaaaaa-0000-0000-0000-000000000001", "text": "second", "book": "B", "section": "s", "paragraph": 2},
        {"id": "bbbbbbbb-0000-0000-0000-000000000002", "text": "first", "book": "B", "section": "s", "paragraph": 1},
        {"id": "cccccccc-0000-0000-0000-000000000003", "text": "third", "book": "B", "section": "s", "paragraph": 3},
    ]

    class Point:
        def __init__(self, members):
            self.id = "abcdef12-0000-0000-0000-000000000000"
            self.payload = {"summary": "they talk", "members": members}

    def test_members_are_returned_in_reading_order(self):
        by_id = {row["id"]: row for row in self.rows}
        with patch("app.agent._row_index", return_value=(by_id, self.rows)):
            ordered = _scene_member_rows("test", [row["id"] for row in self.rows])
        self.assertEqual([row["text"] for row in ordered], ["first", "second", "third"])

    def test_compact_scene_keeps_four_snippets_and_exposes_every_id(self):
        members = [row["id"] for row in self.rows]
        by_id = {row["id"]: row for row in self.rows}
        agent = state()
        with patch("app.agent._row_index", return_value=(by_id, self.rows)):
            payload = _scene_payload(agent, self.Point(members), 4.2, full=False)
        self.assertEqual(payload["scene_id"], "abcdef12")
        self.assertEqual(len(payload["passages"]), 3)
        self.assertEqual(payload["passages"][0]["text"], "first")
        self.assertEqual(len(payload["passage_ids"]), 3)
        self.assertEqual(len(agent.evidence), 3)

    def test_full_scene_reads_every_member_at_length(self):
        members = [row["id"] for row in self.rows]
        by_id = {row["id"]: row for row in self.rows}
        agent = state()
        with patch("app.agent._row_index", return_value=(by_id, self.rows)):
            payload = _scene_payload(agent, self.Point(members), 4.2, full=True)
        self.assertTrue(payload["passages"])
        self.assertEqual(payload["more_passages"], 0)

    def test_read_scene_remembers_what_it_returns(self):
        agent = state()
        by_id = {row["id"]: row for row in self.rows}
        with patch("app.agent._scene_lookup", return_value=(self.Point([row["id"] for row in self.rows]), "")), \
                patch("app.agent._row_index", return_value=(by_id, self.rows)):
            payload = _tool_read_scene(agent, {"scene_id": "abcdef12"})
        self.assertEqual(payload["scene_id"], "abcdef12")
        self.assertEqual(len(payload["passages"]), 3)
        self.assertEqual(len(agent.evidence), 3)

    def test_a_short_scene_id_is_not_guessed(self):
        payload = _tool_read_scene(state(), {"scene_id": "abc"})
        self.assertIn("too short", payload["error"])


class TrueAccountQueries(unittest.TestCase):
    data = {
        "cards": [
            {"key": "gottfried vanger", "mentions": 200, "facts": ["Gottfried was the son of Richard and Margareta."]},
            {"key": "harriet vanger", "mentions": 300, "facts": ["Harriet was Gottfried's daughter."]},
            {"key": "martin vanger", "mentions": 250, "facts": ["Gottfried molested Martin."]},
            {"key": "cabin", "mentions": 100, "facts": ["Gottfried's cabin was on a point."]},
        ],
        "edges": [
            {"from": "harriet vanger", "to": "gottfried vanger", "relation": "daughter of",
             "text": "Harriet — daughter of Gottfried: Harriet was Gottfried's sister."},
            {"from": "gottfried vanger", "to": "cabin", "relation": "home of", "text": "Gottfried lived in the cabin."},
        ],
        "alias": {},
        "mentions": {"gottfried vanger": 200, "harriet vanger": 300, "martin vanger": 250, "cabin": 100},
    }

    def test_role_follows_the_relation_direction(self):
        self.assertEqual(_relation_role(self.data, "gottfried vanger", "harriet vanger"), "father")

    def test_sentence_query_names_the_other_person_doing_the_event(self):
        queries = _true_account_queries("Gottfried Vanger", "Harriet Vanger", "drowned", "father", "her")
        self.assertIn("Harriet drowned her father", queries)
        self.assertNotIn("Harriet Vanger", " ".join(queries))

    def test_cards_suggest_the_relative_not_the_place(self):
        agent = state()
        agent.question = "How Gottfried really died?"
        others = _candidate_others(agent, "gottfried vanger", self.data)
        self.assertEqual(others, ["harriet vanger"])

    def test_died_is_widened_to_a_verb_that_can_name_a_killer(self):
        agent = state()
        self.assertEqual(_event_verb(agent, {"event": "died"}), "killed")
        self.assertEqual(_event_verb(agent, {"event": "drowned"}), "drowned")
        agent.question = "How Gottfried really died?"
        self.assertEqual(_event_verb(agent, {}), "killed")

    def test_reveal_scene_outranks_the_official_accident(self):
        class Point:
            def __init__(self, summary):
                self.payload = {"summary": summary}
        reveal = (Point("Harriet reveals that she killed her father by holding him under the water with an oar."), 5.0)
        official = (Point("Gottfried died by accidental drowning in 1965."), 8.0)
        self.assertGreater(_true_scene_rank(reveal), _true_scene_rank(official))


class MomentHelpers(unittest.TestCase):
    def test_recognises_a_detail_at_a_moment_question(self):
        self.assertTrue(_is_moment_question("What did Salander said when she saw Mikael in the kitchen?"))
        self.assertTrue(_is_moment_question(
            "When Mikael found Salander on the kitchen bench, he loosened the gun. And then what did she say?"))
        self.assertTrue(_is_moment_question("What t-shirt was Salander wearing when they first met with Mikael?"))
        self.assertFalse(_is_moment_question("How did Gottfried really die?"))

    def test_moment_core_drops_the_detail_clause(self):
        self.assertEqual(_moment_core("Salander saw Mikael Blomkvist in the kitchen when she was severely wounded"),
                         "Salander saw Mikael Blomkvist in the kitchen")

    def test_speech_excerpt_reaches_the_quoted_line(self):
        text = ("He reached out his hand and loosened the gun from her grip. Then he heard her mutter in such a low "
                "voice that he could only with difficulty catch the words. Kalle Fucking Blomkvist . She closed her eyes.")
        excerpt = _speech_excerpt(text)
        self.assertIn("mutter", excerpt)
        self.assertIn("Kalle Fucking Blomkvist", excerpt)

    def test_finish_keeps_an_answer_that_cites_short_passage_ids(self):
        agent = state()
        agent.evidence = {"90239c47": {"id": "90239c47-0000-0000-0000-000000000000",
                                       "text": "She muttered Kalle Fucking Blomkvist."}}
        agent.order = ["90239c47"]
        with patch("app.agent._synthesize") as synthesize:
            result = _finish(agent, "She muttered: Kalle Fucking Blomkvist [90239c47].", ["90239c47"], stopped="content")
        synthesize.assert_not_called()
        self.assertIn("Kalle Fucking Blomkvist", result["answer"])

    def test_synthesis_keeps_the_passages_read_on_purpose(self):
        agent = state()
        agent.evidence = {f"{index:08x}": {"id": f"{index:08x}-0000-0000-0000-000000000000", "text": f"row {index}"}
                          for index in range(8)}
        agent.order = list(agent.evidence)
        agent.focus = ["00000007"]
        with patch("app.agent._reranker") as reranker:
            reranker.return_value.predict.return_value = [0.0] * 7
            rows = _synthesis_rows(agent, limit=3)
        self.assertEqual(rows[0]["id"], "00000007-0000-0000-0000-000000000000")


class Coverage(unittest.TestCase):
    def test_detects_the_stage_an_answer_covers(self):
        self.assertEqual(_covered_stages("Salander discovers a body in the water."), {"discovery"})
        covered = _covered_stages("She confronted Niedermann and nailed his feet to the floor.")
        self.assertTrue({"confrontation"} <= covered)

    def test_only_what_happened_questions_get_the_sequence_check(self):
        self.assertTrue(_WHAT_HAPPENED.search("What happened to Salander in the abandoned factory?"))
        self.assertFalse(_WHAT_HAPPENED.search("How did Gottfried really die?"))

    def test_submit_rejects_an_answer_that_stops_after_discovery(self):
        agent = state()
        agent.question = "What happened to Salander in the abandoned factory?"
        agent.evidence = {"a1b2c3d4": {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "She found a body."}}
        agent.order = ["a1b2c3d4"]
        with patch("app.agent._coverage_hint", return_value={"people_involved": ["ronald niedermann"]}):
            payload, stop = _tool_submit_answer(agent, {"answer": "She finds a body in the water [a1b2c3d4].",
                                                        "passage_ids": ["a1b2c3d4"]})
        self.assertFalse(stop)
        self.assertIn("one stage", payload["error"])
        self.assertEqual(payload["people_involved"], ["ronald niedermann"])
        with patch("app.agent._coverage_hint", return_value={}):
            payload, stop = _tool_submit_answer(agent, {"answer": "She finds a body in the water [a1b2c3d4].",
                                                        "passage_ids": ["a1b2c3d4"]})
        self.assertTrue(stop)  # checked once, then the answer is accepted

    def test_moment_tool_returns_the_chosen_scene(self):
        agent = state()
        row = {"id": "a1b2c3d4-0000-0000-0000-000000000000", "text": "Kalle Fucking Blomkvist."}
        with patch("app.agent._moment_scene_hits",
                   return_value=([row | {"scene_summary": "the kitchen"}], "Salander saw him in the kitchen")), \
                patch("app.agent._scene_points", return_value=([], "")), \
                patch("app.agent._alias_variants", return_value=[]):
            payload = _tool_scene_moment(agent, {})
        self.assertEqual(payload["moment"], "Salander saw him in the kitchen")
        self.assertEqual(payload["passages"][0]["id"], "a1b2c3d4")
        self.assertIn("a1b2c3d4", agent.evidence)


class IdsAndHelpers(unittest.TestCase):
    def test_resolves_a_unique_prefix(self):
        row = {"id": "abcdef12-3456-7890-abcd-ef1234567890", "text": "x"}
        with patch("app.agent._row_index", return_value=({row["id"]: row}, [row])):
            self.assertIs(_resolve_id("test", "abcdef12")[0], row)
            self.assertIsNone(_resolve_id("test", "abcde")[0])  # too short to guess
            self.assertIn("no passage", _resolve_id("test", "ffffffff")[1])

    def test_reports_an_ambiguous_prefix(self):
        rows = [{"id": "abcdef12-0000-0000-0000-000000000001"}, {"id": "abcdef12-0000-0000-0000-000000000002"}]
        with patch("app.agent._row_index", return_value=({row["id"]: row for row in rows}, rows)):
            row, error = _resolve_id("test", "abcdef12")
            self.assertIsNone(row)
            self.assertIn("ambiguous", error)

    def test_book_names_and_counts(self):
        self.assertEqual(_book_short("The Girl with the Dragon Tattoo"), "Dragon Tattoo")
        self.assertEqual(_book_short("The Girl Who Played with Fire"), "Played with Fire")
        self.assertEqual(_book_short(None), "?")
        self.assertEqual(_int({"k": 99}, "k", 5), 12)
        self.assertEqual(_int({}, "k", 5), 5)
        self.assertEqual(_int({"k": "x"}, "k", 5), 5)

    def test_every_tool_has_a_schema(self):
        names = [spec["function"]["name"] for spec in _tool_specs()]
        self.assertEqual(names, ["semantic_search", "keyword_search", "expand_query", "search_scenes", "read_scene",
                                 "scene_moment", "true_account", "entity_card", "find_connections", "find_names",
                                 "read_passage", "read_chapter", "submit_answer"])
        for spec in _tool_specs():
            self.assertEqual(spec["type"], "function")
            self.assertEqual(spec["function"]["parameters"]["type"], "object")

    def test_blank_question_is_rejected_before_any_model_call(self):
        with self.assertRaises(ValueError):
            run_agent("   ", "test")


if __name__ == "__main__":
    unittest.main()
