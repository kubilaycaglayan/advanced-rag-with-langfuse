"""Apply captured execution contracts to the unregistered v2.17 graph and boundaries."""
from dataclasses import asdict, fields
import json
import unittest
from unittest.mock import patch

from app.agent import execution, runner, submission
from app.agent.state import AgentRuntime, ExecutionState
from app.pipelines.config import ResolvedPipelineConfig
from app.pipelines.resolver import resolve
from app.settings_definitions import AgentSettings, TargetAgentSettings
import test_agent_execution_contract as contracts


class ExtractedExecutionContract(contracts.AgentExecutionContract):
    """The same 16 behavioral expectations run through the extracted driver."""
    def setUp(self):
        replacement = patch.object(contracts, 'runner', execution)
        replacement.start()
        self.addCleanup(replacement.stop)


class ExecutionBoundaries(unittest.TestCase):
    def state(self, **values):
        return ExecutionState(question='Who wrote the report?', asked='Who wrote the report?',
                              collection='fixture', config=ResolvedPipelineConfig(),
                              settings=TargetAgentSettings(initial_scene_probe=False, min_tool_calls=0),
                              started=execution.time.perf_counter(), **values)

    def test_target_configuration_removes_early_stop_without_rewriting_v2_16(self):
        self.assertNotIn('premise_early_stop', asdict(TargetAgentSettings()))
        with self.assertRaises(TypeError):
            TargetAgentSettings(premise_early_stop=True)
        self.assertIn('premise_early_stop', asdict(resolve().agent_settings))
        with self.assertRaisesRegex(ValueError, 'unknown pipeline'):
            resolve('v2.17')
        with self.assertRaisesRegex(ValueError, 'TargetAgentSettings'):
            execution.run_agent('Who?', 'fixture', settings=AgentSettings(premise_early_stop=True))
        with self.assertRaises(ValueError):
            execution.run_agent(' ', 'fixture')

    def test_state_has_explicit_progress_and_runtime_resources_are_separate(self):
        state = self.state()
        names = {item.name for item in fields(state)}
        self.assertTrue({'messages', 'pending_reply', 'pending_calls', 'next_tool_index',
                         'candidate_answer', 'candidate_passage_ids', 'route', 'final_result',
                         'budget_reason', 'budget_drafted', 'final_prepared'} <= names)
        self.assertFalse({'on_event', 'root_observation', 'tool_specs', 'client'} & names)
        callback = lambda event: None
        runtime = AgentRuntime(on_event=callback, root_observation=object())
        self.assertIs(runtime.on_event, callback)
        self.assertEqual(state.messages, [])
        state.remember([contracts.B, contracts.A, contracts.B])
        self.assertEqual(state.order, ['bbbbbbbb', 'aaaaaaaa'])
        self.assertEqual(list(state.evidence), state.order)

    def test_budget_draft_and_final_preparation_each_execute_once(self):
        state = self.state(budget_reason='turn_budget', route='budget')
        state.remember([contracts.A])
        state.messages = [{'role': 'user', 'content': 'Question'},
                          {'role': 'tool', 'content': 'LATEST RESULT [aaaaaaaa]'}]
        runtime = AgentRuntime()
        with patch.object(submission, '_tracked_agent_chat', return_value=contracts.reply('Ada wrote it [aaaaaaaa].')) as chat, \
             patch.object(execution, 'prepare_final_answer', wraps=submission.prepare_final_answer) as finish:
            execution.draft_budget(state, runtime)
            self.assertEqual(state.route, 'final')
            self.assertTrue(state.budget_drafted)
            self.assertIsNone(state.final_result)
            finish.assert_not_called()
            execution.draft_budget(state, runtime)
            execution.finalize_answer(state, runtime)
            result = state.final_result
            execution.finalize_answer(state, runtime)
            execution.draft_budget(state, runtime)
            chat.assert_called_once()
            finish.assert_called_once()
            self.assertIs(state.final_result, result)
            self.assertEqual(state.route, 'done')
            self.assertEqual(result['stopped'], 'budget')
            self.assertEqual(chat.call_args.args[3], 'forced answer')
            self.assertIn('LATEST RESULT', str(chat.call_args.args[1]))
            self.assertNotIn('Ada wrote the report.', str(chat.call_args.args[1]))

    def test_tool_boundary_exposes_pending_work_and_candidate_before_finalization(self):
        with patch.object(contracts, 'runner', execution), contracts.ExecutionHarness([
                contracts.reply(calls=[contracts.submit(), contracts.call('must_not_run')]),
                contracts.reply('{"supported":true}'),
        ], seed=[contracts.A]) as h:
            with patch.object(execution, 'finalize_answer') as final:
                # Execute boundaries directly, without either driver or graph routing.
                state = self.state()
                execution.prepare_question(state, AgentRuntime())
                runtime = AgentRuntime(tool_specs=execution._tool_specs())
                execution.decide_next_turn(state, runtime)
                self.assertEqual(state.route, 'select')
                execution.select_model_turn(state, runtime)
                self.assertEqual(state.route, 'tools')
                self.assertEqual(len(state.pending_calls), 2)
                execution.process_reply_tools(state, runtime)
                self.assertEqual(state.next_tool_index, 1)
                self.assertEqual(state.route, 'final')
                self.assertEqual(state.candidate_answer, 'Ada wrote it [E1].')
                self.assertTrue(state.verification_supported)
                self.assertIsNone(state.final_result)
                final.assert_not_called()

    def test_premise_probe_still_gathers_survival_evidence_before_normal_model_selection(self):
        from app.agent.prechecks import _premise_probe
        alive = dict(contracts.A, text='Harriet said, I am alive.')
        with patch.object(contracts, 'runner', execution), contracts.ExecutionHarness([
                contracts.reply('No one killed Harriet; she is alive [aaaaaaaa].'),
                contracts.reply('{"supported":true}'),
        ], question='Who killed Harriet?',
                settings=TargetAgentSettings(initial_scene_probe=False, min_tool_calls=0)) as h:
            with patch.object(execution, '_premise_probe', side_effect=_premise_probe), \
                 patch('app.agent.prechecks._semantic_rows', return_value=[alive]):
                result = h.run()
            self.assertEqual(h.state.premise_evidence, ['aaaaaaaa'])
            self.assertEqual(h.state.focus, ['aaaaaaaa'])
            self.assertIn('Premise check:', h.calls[0]['messages'][-1]['content'])
            self.assertEqual([c['purpose'] for c in h.calls],
                             ['tool selection and answer', 'submission verification'])
            self.assertEqual(result['stopped'], 'content')
            self.assertNotIn('premise_resolved', result['stopped'])

    def test_target_manifest_covers_relocated_builders_and_has_its_own_identity(self):
        from app.agent.instructions import (instruction_fingerprint, instruction_manifest,
                                            target_instruction_fingerprint, target_instruction_manifest)
        from pathlib import Path
        import ast
        manifest = target_instruction_manifest()
        self.assertNotIn('run_agent', manifest['messages'])
        for name in ('prepare_question', 'select_model_turn', 'process_reply_tools',
                     'review_answer_text', 'draft_budget_answer', 'prepare_final_answer'):
            self.assertIn(name, manifest['messages'])
        self.assertEqual(manifest['system'], instruction_manifest()['system'])
        self.assertEqual(manifest['tools'], instruction_manifest()['tools'])
        self.assertNotEqual(target_instruction_fingerprint(), instruction_fingerprint())
        baseline = instruction_fingerprint()
        target = target_instruction_fingerprint()
        parse = ast.parse
        def tamper(source):
            if source.startswith('def review_answer_text'):
                source = source.replace('Submit a supported answer with passage IDs, or say the evidence is insufficient.',
                                        'Changed relocated instruction.')
            return parse(source)
        with patch('app.agent.instructions.ast.parse', side_effect=tamper):
            self.assertNotEqual(target_instruction_fingerprint(), target)
            self.assertEqual(instruction_fingerprint(), baseline)
        tree = ast.parse(Path(execution.__file__).read_text())
        identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn('_direct_premise_resolution', identifiers)
        self.assertIn('_premise_probe', identifiers)
        self.assertNotIn('_forced_answer', identifiers)
        self.assertNotIn('_finish', identifiers)
        self.assertIn('invoke_graph', identifiers)

    def test_full_transcripts_results_and_evidence_match_the_released_runner(self):
        scenarios = [
            ([contracts.reply(calls=[contracts.call('semantic_search'), contracts.call('keyword_search')]),
              contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}')], []),
            ([contracts.reply(calls=[contracts.submit(), contracts.submit('Bea read it [bbbbbbbb].', ('bbbbbbbb',))]),
              contracts.reply('{"supported":false,"reason":"wrong"}'), contracts.reply('{"supported":true}')],
             [contracts.A, contracts.B]),
            ([contracts.reply(calls=[contracts.submit('Ada wrote it.', ())]),
              contracts.reply('Ada wrote it [aaaaaaaa].')], [contracts.A]),
            ([contracts.reply(calls=[contracts.call('broken_tool'), contracts.call('semantic_search')]),
              contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}')], []),
        ]
        def run(module, replies, seed):
            with patch.object(contracts, 'runner', module), contracts.ExecutionHarness(replies, seed=seed) as h:
                with patch.object(module.time, 'perf_counter', side_effect=iter(range(200))):
                    result = h.run()
                return {'result': result, 'model_calls': h.calls, 'tools': h.tools, 'events': h.events,
                        'evidence': h.state.evidence, 'order': h.state.order,
                        'focus': h.state.focus, 'retrieval_queries': h.state.retrieval_queries}
        for index, (replies, seed) in enumerate(scenarios):
            with self.subTest(index=index):
                self.assertEqual(run(execution, replies, seed), run(runner, replies, seed))


if __name__ == '__main__':
    unittest.main()
