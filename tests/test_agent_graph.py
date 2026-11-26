"""Real StateGraph routing, framework limits and per-run context isolation."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from langgraph.errors import GraphRecursionError

from app.agent import execution, graph
from app.agent.state import AgentRuntime, ExecutionState
from app.pipelines.config import ResolvedPipelineConfig
from app.settings_definitions import TargetAgentSettings
import test_agent_execution_contract as contracts


class AgentGraph(unittest.TestCase):
    def run_recorded(self, replies, *, settings=None, seed=()):
        visited = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(contracts, 'runner', execution))
            h = stack.enter_context(contracts.ExecutionHarness(replies, settings=settings, seed=seed))
            for name, function_name in graph.BOUNDARIES.items():
                original = getattr(execution, function_name)
                def record(state, runtime, original=original, name=name):
                    visited.append(name)
                    return original(state, runtime)
                stack.enter_context(patch.object(execution, function_name, side_effect=record))
            result = h.run()
        return result, visited, h

    def test_text_answer_and_submission_take_distinct_graph_paths(self):
        for submitted, expected in [(False, 'review'), (True, 'tools')]:
            with self.subTest(submitted=submitted):
                first = contracts.reply(calls=[contracts.submit()]) if submitted else contracts.reply('Ada wrote it [aaaaaaaa].')
                result, visited, h = self.run_recorded([first, contracts.reply('{"supported":true}')], seed=[contracts.A])
                self.assertEqual(visited, ['prepare', 'decide', 'select', expected, 'final'])
                self.assertEqual(h.state.route, 'done')
                self.assertEqual(result['stopped'], 'submit' if submitted else 'content')
                self.assertTrue(h.state.final_prepared)
                self.assertFalse(h.state.budget_drafted)
                h.finish.assert_called_once()

    def test_tool_budget_routes_directly_to_draft_then_final(self):
        settings = TargetAgentSettings(initial_scene_probe=False, min_tool_calls=0, max_tool_calls=1)
        result, visited, h = self.run_recorded([
            contracts.reply(calls=[contracts.call('semantic_search'), contracts.call('must_not_run')]),
            contracts.reply('Ada wrote it [aaaaaaaa].'),
        ], settings=settings)
        self.assertEqual(visited, ['prepare', 'decide', 'select', 'tools', 'budget', 'final'])
        self.assertEqual(h.state.budget_reason, 'tool_budget')
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual([c['purpose'] for c in h.calls], ['tool selection and answer', 'forced answer'])
        h.finish.assert_called_once()

    def test_timeout_routes_without_selecting_a_model_turn(self):
        settings = TargetAgentSettings(initial_scene_probe=False, min_tool_calls=0, timeout_seconds=0)
        result, visited, h = self.run_recorded([contracts.reply('Ada wrote it [aaaaaaaa].')], settings=settings, seed=[contracts.A])
        self.assertEqual(visited, ['prepare', 'decide', 'budget', 'final'])
        self.assertEqual(h.state.budget_reason, 'timeout')
        self.assertEqual(result['turns'], 1)
        self.assertEqual([c['purpose'] for c in h.calls], ['forced answer'])
        h.finish.assert_called_once()

    def test_framework_limit_allows_entire_application_turn_budget_and_final_handoff(self):
        for turns in (0, 1, 10, 50):
            with self.subTest(turns=turns):
                settings = TargetAgentSettings(initial_scene_probe=False, min_tool_calls=0, max_turns=turns)
                replies = [contracts.reply('Keep investigating.') for _ in range(turns)]
                replies.append(contracts.reply('Ada wrote it [aaaaaaaa].'))
                result, visited, h = self.run_recorded(replies, settings=settings, seed=[contracts.A])
                self.assertEqual(visited, ['prepare'] + ['decide', 'select', 'review'] * turns + ['decide', 'budget', 'final'])
                self.assertEqual(len(visited), graph.execution_limit(settings) - 1)
                self.assertEqual(result['stopped'], 'budget')
                self.assertEqual(result['turns'], turns)
                self.assertEqual(h.state.budget_reason, 'turn_budget')
                self.assertEqual(len(h.calls), turns + 1)
                self.assertEqual(h.calls[-1]['purpose'], 'forced answer')
                h.finish.assert_called_once()

    def test_rejected_calls_do_not_add_graph_steps_or_enforce_an_extra_tool_limit(self):
        settings = TargetAgentSettings(initial_scene_probe=False, min_tool_calls=0, max_tool_calls=1)
        result, visited, h = self.run_recorded([
            contracts.reply(calls=[contracts.submit() for _ in range(25)] + [contracts.submit('Bea read it [bbbbbbbb].', ('bbbbbbbb',))]),
            contracts.reply('{"supported":false,"reason":"wrong"}'), contracts.reply('{"supported":true}'),
        ], settings=settings, seed=[contracts.A, contracts.B])
        self.assertEqual(visited, ['prepare', 'decide', 'select', 'tools', 'final'])
        self.assertEqual(result['tool_calls'], 26)
        self.assertEqual(result['stopped'], 'submit')
        self.assertNotIn('tool_budget', [event['type'] for event in h.events])
        self.assertEqual([c['purpose'] for c in h.calls],
                         ['tool selection and answer', 'submission verification', 'submission verification'])

    def test_framework_errors_propagate_instead_of_triggering_a_provider_fallback(self):
        with patch.object(contracts, 'runner', execution), contracts.ExecutionHarness([], seed=[contracts.A]) as h:
            state = ExecutionState(question='Q', asked='Q', collection='fixture',
                                   config=ResolvedPipelineConfig(), settings=h.settings, started=execution.time.perf_counter())
            with self.assertRaises(GraphRecursionError):
                graph.build_graph().invoke({'agent': state}, context=AgentRuntime(), config={'recursion_limit': 2})
            self.assertFalse(state.budget_drafted)
            h.finish.assert_not_called()
            self.assertNotIn('forced answer', [c['purpose'] for c in h.calls])

    def test_tool_results_continue_to_another_selection_turn(self):
        result, visited, h = self.run_recorded([
            contracts.reply(calls=[contracts.call('semantic_search')]),
            contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}'),
        ])
        self.assertEqual(visited, ['prepare', 'decide', 'select', 'tools', 'decide', 'select', 'review', 'final'])
        self.assertEqual(result['turns'], 2)
        self.assertEqual(h.calls[1]['messages'][-1]['tool_call_id'], 'agent_1_1')

    def test_reference_matches_compiled_nodes_edges_and_catalog_signature(self):
        from app.agent.graph_reference import REFERENCE, render_reference
        from app.pipelines.catalog import load_catalog
        source = render_reference()
        self.assertEqual(REFERENCE.read_text(), source)
        self.assertIn(f'v2.17 candidate — {load_catalog().default} released baseline', source)
        topology = graph.build_graph().get_graph()
        self.assertEqual(set(topology.nodes), {'__start__', '__end__', *graph.BOUNDARIES})
        for edge in topology.edges:
            annotation = f'|{edge.data}|' if edge.data else ''
            self.assertIn(f'{edge.source} -->{annotation} {edge.target}', source)

    def test_compiled_graph_reuses_topology_without_sharing_state_or_callbacks(self):
        shared = graph.build_graph()
        _, _, first = self.run_recorded([contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}')], seed=[contracts.A])
        _, _, second = self.run_recorded([contracts.reply('Bea read it [bbbbbbbb].'), contracts.reply('{"supported":true}')], seed=[contracts.B])
        self.assertIs(graph.build_graph(), shared)
        self.assertIsNot(first.state, second.state)
        self.assertEqual(first.state.order, ['aaaaaaaa'])
        self.assertEqual(second.state.order, ['bbbbbbbb'])
        self.assertNotEqual(first.events, [])
        self.assertEqual(len(first.events), len(second.events))
        self.assertNotIn('aaaaaaaa', str(second.calls))
        self.assertIsNone(shared.checkpointer)


if __name__ == '__main__':
    unittest.main()
