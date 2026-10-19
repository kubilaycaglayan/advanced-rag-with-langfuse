"""Agent tool protocol: tool parsing, citation mapping, answer guards and context compaction."""
import json
import os
import unittest
from unittest.mock import patch

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app.agent import (AgentSettings, AgentState, _book_short, _compact, _final, _int, _parse_text_tool,
                       _resolve_id, _tool_specs, _tool_submit_answer, run_agent)
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
        self.assertEqual(names, ["semantic_search", "keyword_search", "expand_query", "search_scenes", "entity_card",
                                 "find_names", "read_passage", "read_chapter", "submit_answer"])
        for spec in _tool_specs():
            self.assertEqual(spec["type"], "function")
            self.assertEqual(spec["function"]["parameters"]["type"], "object")

    def test_blank_question_is_rejected_before_any_model_call(self):
        with self.assertRaises(ValueError):
            run_agent("   ", "test")


if __name__ == "__main__":
    unittest.main()
