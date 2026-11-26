"""Executable v2.16 orchestration contracts for the v2.17 migration.

Only retrieval/provider boundaries and telemetry are replaced. The runner, submission
validation, verifier prompt construction, handoff, synthesis and final result execute
normally. No graph or settings refactor belongs in this capture step.
"""
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from dataclasses import replace
import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

from app.agent import runner, submission
from app.agent.state import AgentSettings
from app.agent.tools.submission import _tool_submit_answer
from app.pipelines.config import ResolvedPipelineConfig


A = {'id': 'aaaaaaaa-0000', 'text': 'Ada wrote the report.', 'book': 'Book',
     'book_file': 'book.epub', 'section': 'one', 'paragraph': 1}
B = {'id': 'bbbbbbbb-0000', 'text': 'Bea read the report.', 'book': 'Book',
     'book_file': 'book.epub', 'section': 'one', 'paragraph': 2}
C = {'id': 'cccccccc-0000', 'text': 'Cora challenged the report.', 'book': 'Book',
     'book_file': 'book.epub', 'section': 'one', 'paragraph': 3}


def call(name, arguments=None, identifier=None):
    value = {'function': {'name': name, 'arguments': arguments or {}}}
    if identifier:
        value['id'] = identifier
    return value


def reply(content='', calls=()):
    return {'message': {'content': content, 'tool_calls': list(calls)}}


def submit(answer='Ada wrote it [aaaaaaaa].', ids=('aaaaaaaa',)):
    return call('submit_answer', {'answer': answer, 'passage_ids': list(ids)})


class ExecutionHarness:
    """Finite scripted model replies; any unexpected call or network access fails."""
    def __init__(self, replies, *, seed=(), settings=None, question='Who wrote the report?', tools=None):
        self.replies = iter(replies)
        self.seed = seed
        self.settings = settings or AgentSettings(initial_scene_probe=False, min_tool_calls=0)
        self.question = question
        self.tool_handler = tools
        self.events = []
        self.calls = []
        self.tools = []
        self.state = None
        self.stack = ExitStack()

    def __enter__(self):
        def normalize(state):
            self.state = state
            state.remember(list(self.seed))
            return state.question, []

        def chat(state, messages, specs, purpose):
            self.calls.append({'purpose': purpose, 'messages': deepcopy(messages),
                               'tools': deepcopy(specs), 'turns': state.turns,
                               'tool_calls': state.tool_calls, 'order': list(state.order)})
            value = next(self.replies)
            if isinstance(value, Exception):
                raise value
            return deepcopy(value)

        def dispatch(state, name, arguments):
            self.tools.append((name, deepcopy(arguments), state.tool_calls))
            if self.tool_handler:
                return self.tool_handler(state, name, arguments)
            if name == 'submit_answer':
                return _tool_submit_answer(state, arguments)
            if name == 'broken_tool':
                raise ValueError('retrieval failed')
            rows = [A, B] if name == 'semantic_search' else [B, A, C]
            state.remember(rows, arguments.get('query'))
            return {'hits': [{'id': row['id'][:8]} for row in rows]}, False

        self.stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')))
        for name in ('_connection_precheck', '_true_account_precheck', '_sequence_precheck',
                     '_moment_precheck', '_premise_probe'):
            self.stack.enter_context(patch.object(runner, name, return_value=None))
        self.stack.enter_context(patch.object(runner, '_normalize_question', side_effect=normalize))
        for module in (runner, submission):
            self.stack.enter_context(patch.object(module, 'observation', side_effect=lambda *a, **kw: nullcontext(None)))
            self.stack.enter_context(patch.object(module, 'update_observation'))
            self.stack.enter_context(patch.object(module, '_tracked_agent_chat', side_effect=chat))
        self.stack.enter_context(patch.object(submission, 'passage_index', return_value=({}, [A, B, C])))
        self.stack.enter_context(patch.object(runner, '_run_tool', side_effect=dispatch))
        self.coverage = self.stack.enter_context(patch.object(runner, '_coverage_gap', return_value=None))
        self.stack.enter_context(patch('app.agent.tools.submission._coverage_gap', return_value=None))
        self.finish = Mock(wraps=submission._finish)
        for module in (runner, submission):
            self.stack.enter_context(patch.object(module, '_finish', new=self.finish))
        return self

    def run(self):
        return runner.run_agent(self.question, 'fixture', ResolvedPipelineConfig(),
                                settings=self.settings, on_event=self.events.append)

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


class AgentExecutionContract(unittest.TestCase):
    def assert_result(self, h, result, *, stopped, turns, tools, ids):
        self.assertEqual(result['stopped'], stopped)
        self.assertEqual((result['turns'], result['tool_calls']), (turns, tools))
        self.assertEqual(result['passage_ids'], ids)
        self.assertEqual([row['id'][:8] for row in result['evidence']], ids)
        self.assertEqual(result['collected_passages'], len(h.state.evidence))
        self.assertEqual(result['question'], h.question)
        self.assertEqual(result['asked'], h.question)
        self.assertEqual(result['model'], h.settings.model)
        self.assertEqual(result['usage'], {})
        self.assertEqual(result['trace'], h.state.trace)
        self.assertIsInstance(result['latency_seconds'], (int, float))
        self.assertEqual(set(result) - {'submitted'}, {
            'question', 'asked', 'name_normalization', 'answer', 'raw_answer', 'passage_ids',
            'citations', 'evidence', 'collected_passages', 'turns', 'tool_calls', 'trace',
            'model', 'usage', 'latency_seconds', 'stopped',
        })
        h.finish.assert_called_once()

    def test_multiple_calls_are_sequential_and_accepted_submission_stops_remaining_calls(self):
        with ExecutionHarness([
            reply(calls=[call('semantic_search', {'query': 'first'}),
                         call('keyword_search', json.dumps({'query': 'second'}), 'explicit'),
                         submit('Bea read it [bbbbbbbb]; Ada wrote it [aaaaaaaa].', ('bbbbbbbb', 'aaaaaaaa')),
                         call('must_not_run')]),
            reply('{"supported":true,"reason":"stated"}'),
        ]) as h:
            result = h.run()
            self.assertEqual([t[0] for t in h.tools], ['semantic_search', 'keyword_search', 'submit_answer'])
            self.assertEqual([t[2] for t in h.tools], [1, 2, 3])
            self.assertEqual(h.tools[1][1], {'query': 'second'})
            self.assertEqual(h.state.order, ['aaaaaaaa', 'bbbbbbbb', 'cccccccc'])
            self.assertEqual([c['purpose'] for c in h.calls], ['tool selection and answer', 'submission verification'])
            conversation = h.finish.call_args.args[0]
            self.assertIs(conversation, h.state)
            self.assert_result(h, result, stopped='submit', turns=1, tools=3, ids=['bbbbbbbb', 'aaaaaaaa'])
            self.assertEqual(result['answer'], 'Bea read it [E1]; Ada wrote it [E2].')
            self.assertEqual(result['raw_answer'], 'Bea read it [bbbbbbbb]; Ada wrote it [aaaaaaaa].')
            self.assertEqual(result['citations'], ['E1', 'E2'])
            self.assertEqual(result['submitted']['passage_ids'], ['bbbbbbbb', 'aaaaaaaa'])

    def test_next_turn_sees_tool_messages_and_generated_ids_in_order(self):
        with ExecutionHarness([
            reply('Investigating', [call('semantic_search'), call('keyword_search', identifier='given')]),
            reply('Ada wrote it [aaaaaaaa].'), reply('{"supported":true}'),
        ]) as h:
            result = h.run()
            messages = h.calls[1]['messages']
            self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'tool', 'tool'])
            self.assertEqual([c['id'] for c in messages[2]['tool_calls']], ['agent_1_1', 'given'])
            self.assertEqual([m['tool_call_id'] for m in messages[3:]], ['agent_1_1', 'given'])
            self.assertEqual(json.loads(messages[3]['content'])['hits'], [{'id': 'aaaaaaaa'}, {'id': 'bbbbbbbb'}])
            self.assert_result(h, result, stopped='content', turns=2, tools=2, ids=['aaaaaaaa'])

    def test_text_form_tool_call_executes_and_is_recorded_as_an_assistant_tool_request(self):
        with ExecutionHarness([
            reply('```json\n{"tool":"semantic_search","arguments":{"query":"report"}}\n```'),
            reply('Ada wrote it [aaaaaaaa].'), reply('{"supported":true}'),
        ]) as h:
            result = h.run()
            self.assertEqual(h.tools, [('semantic_search', {'query': 'report'}, 1)])
            messages = h.calls[1]['messages']
            self.assertEqual(messages[2]['tool_calls'][0]['id'], 'agent_1_1')
            self.assertIn('```json', messages[2]['content'])
            self.assertEqual(messages[3]['tool_call_id'], 'agent_1_1')
            self.assert_result(h, result, stopped='content', turns=2, tools=1, ids=['aaaaaaaa'])

    def test_rejected_verification_and_repeated_answer_skip_budget_check_and_continue_same_reply(self):
        settings = AgentSettings(initial_scene_probe=False, min_tool_calls=0, max_tool_calls=1)
        with ExecutionHarness([
            reply(calls=[submit(), submit(), submit('Bea read it [bbbbbbbb].', ('bbbbbbbb',)), call('must_not_run')]),
            reply('{"supported":false,"reason":"contradiction"}'), reply('{"supported":true}'),
        ], seed=[A, B], settings=settings) as h:
            result = h.run()
            self.assertEqual([t[2] for t in h.tools], [1, 2, 3])
            self.assertEqual([c['purpose'] for c in h.calls],
                             ['tool selection and answer', 'submission verification', 'submission verification'])
            self.assertEqual(h.state.rejected_answers, {'ada wrote it .'})
            self.assertNotIn('tool_budget', [e['type'] for e in h.events])
            self.assert_result(h, result, stopped='submit', turns=1, tools=3, ids=['bbbbbbbb'])

    def test_rejected_submission_feedback_precedes_later_tools_and_next_turn(self):
        settings = AgentSettings(initial_scene_probe=False, min_tool_calls=0, max_tool_calls=2)
        with ExecutionHarness([
            reply(calls=[submit(), call('keyword_search')]), reply('{"supported":false,"reason":"contradiction"}'),
            reply('Bea read it [bbbbbbbb].'),
        ], seed=[A], settings=settings) as h:
            result = h.run()  # second call reaches the ordinary budget exit
            self.assertEqual([c['purpose'] for c in h.calls],
                             ['tool selection and answer', 'submission verification', 'forced answer'])
            messages = h.calls[-1]['messages']
            self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'tool', 'tool', 'user'])
            self.assertEqual([m['tool_call_id'] for m in messages[3:5]], ['agent_1_1', 'agent_1_2'])
            self.assertIn('contradiction', messages[3]['content'])
            self.assertIn('bbbbbbbb', messages[4]['content'])
            self.assert_result(h, result, stopped='budget', turns=1, tools=2, ids=['bbbbbbbb'])

    def test_tool_level_submission_rejection_uses_ordinary_budget_check(self):
        settings = AgentSettings(initial_scene_probe=False, min_tool_calls=4, max_tool_calls=1)
        with ExecutionHarness([reply(calls=[submit(), call('must_not_run')]),
                               reply('Ada wrote it [aaaaaaaa].')], seed=[A], settings=settings) as h:
            result = h.run()
            self.assertEqual(len(h.tools), 1)
            self.assertIn('investigate more', h.calls[-1]['messages'][-2]['content'])
            self.assert_result(h, result, stopped='budget', turns=1, tools=1, ids=['aaaaaaaa'])

    def test_empty_id_submission_is_accepted_without_verification_and_can_synthesize(self):
        with ExecutionHarness([reply(calls=[submit('Ada wrote it.', ())]),
                               reply('Ada wrote it [aaaaaaaa].')], seed=[A]) as h:
            result = h.run()
            self.assertEqual([c['purpose'] for c in h.calls], ['tool selection and answer', 'answer synthesis'])
            self.assertEqual(result['submitted']['passage_ids'], [])
            self.assertEqual(result['raw_answer'], 'Ada wrote it [aaaaaaaa].')
            self.assert_result(h, result, stopped='submit+synthesis', turns=1, tools=1, ids=['aaaaaaaa'])

    def test_all_budget_exits_handoff_latest_conversation_and_finish_once(self):
        for reason in ('timeout', 'tool_budget', 'turn_budget'):
            with self.subTest(reason=reason):
                settings = AgentSettings(initial_scene_probe=False, min_tool_calls=0, max_turns=1,
                                         max_tool_calls=1 if reason == 'tool_budget' else 16,
                                         timeout_seconds=0 if reason == 'timeout' else 900)
                replies = ([reply(calls=[call('semantic_search')])] if reason != 'timeout' else [])
                replies.append(reply('Ada wrote it [aaaaaaaa].'))
                with ExecutionHarness(replies, seed=[A], settings=settings) as h:
                    # Monotonic deterministic elapsed time makes timeout independent of machine speed.
                    with patch.object(runner.time, 'perf_counter', side_effect=iter(range(100))):
                        result = h.run()
                    forced = h.calls[-1]
                    self.assertEqual(forced['purpose'], 'forced answer')
                    self.assertIsNone(forced['tools'])
                    self.assertIn('Do not call tools.', forced['messages'][-1]['content'])
                    self.assertNotIn('Ada wrote the report.', str(forced['messages']))  # stored evidence is not injected
                    if reason != 'timeout':
                        self.assertEqual(forced['messages'][-2]['tool_call_id'], 'agent_1_1')
                        self.assertIn('bbbbbbbb', forced['messages'][-2]['content'])
                    else:
                        self.assertEqual(len(forced['messages']), 3)
                    self.assertEqual([e['type'] for e in h.events].count(reason), 1)
                    self.assert_result(h, result, stopped='budget', turns=1,
                                       tools=0 if reason == 'timeout' else 1, ids=['aaaaaaaa'])

    def test_final_sequence_rewrite_after_verification_is_not_verified_again(self):
        with ExecutionHarness([reply('She found evidence [aaaaaaaa].'), reply('{"supported":true}'),
                               reply('She arrived, found evidence, confronted him and escaped [bbbbbbbb].')],
                              seed=[A, B], question='What happened to Ada?') as h:
            with patch.object(submission, '_coverage_hint', return_value={}) as hint:
                result = h.run()
            hint.assert_called_once()
            self.assertEqual([c['purpose'] for c in h.calls],
                             ['tool selection and answer', 'submission verification', 'answer synthesis'])
            self.assertIn('confronted', result['answer'])
            self.assert_result(h, result, stopped='content', turns=1, tools=0, ids=['bbbbbbbb'])

    def test_tool_errors_are_counted_and_returned_before_continuing(self):
        with ExecutionHarness([reply(calls=[call('broken_tool'), call('semantic_search')]),
                               reply('Ada wrote it [aaaaaaaa].'), reply('{"supported":true}')]) as h:
            result = h.run()
            self.assertEqual(h.state.trace[0]['error'], 'ValueError: retrieval failed')
            self.assertEqual(h.calls[1]['messages'][3]['tool_call_id'], 'agent_1_1')
            self.assertIn('ValueError: retrieval failed', h.calls[1]['messages'][3]['content'])
            self.assertEqual([t[2] for t in h.tools], [1, 2])
            self.assert_result(h, result, stopped='content', turns=2, tools=2, ids=['aaaaaaaa'])

    def test_preparation_execution_and_message_order_are_distinct(self):
        settings = AgentSettings(initial_scene_probe=True, min_tool_calls=0)
        order = []
        with ExecutionHarness([reply('Ada wrote it [aaaaaaaa].'), reply('{"supported":true}')],
                              seed=[A], settings=settings) as h, ExitStack() as stack:
            def prepared(name, value):
                def run(state):
                    order.append(name)
                    return value
                return run
            payloads = {
                '_connection_precheck': {'person_a': 'Ada', 'person_b': 'Bea', 'facts': []},
                '_initial_scene_probe': ({'passage_ids': ['aaaaaaaa'], 'scene_id': 'scene'}, ''),
                '_true_account_precheck': {'person': 'Ada', 'event': 'wrote'},
                '_sequence_precheck': {'scene_passages': []},
                '_moment_precheck': {'keywords': [], 'scene_rows': []},
                '_premise_probe': 'premise message',
            }
            for name, value in payloads.items():
                stack.enter_context(patch.object(runner, name, side_effect=prepared(name, value)))
            for builder, text in (('_initial_scene_message', 'scene message'),
                                  ('_precheck_message', 'connection message'),
                                  ('_true_account_message', 'true account message'),
                                  ('_sequence_message', 'sequence message'),
                                  ('_moment_message', 'moment message')):
                stack.enter_context(patch.object(runner, builder, return_value=text))
            result = h.run()
            self.assertEqual(order, list(payloads))
            self.assertEqual([m['content'] for m in h.calls[0]['messages'][1:]], [
                h.question, 'scene message', 'connection message', 'true account message',
                'sequence message', 'moment message', 'premise message',
            ])
            self.assertEqual([m['role'] for m in h.calls[0]['messages']], ['system'] + ['user'] * 7)
            self.assert_result(h, result, stopped='content', turns=1, tools=0, ids=['aaaaaaaa'])

    def test_minimum_and_no_tool_nudges_share_two_attempts(self):
        settings = AgentSettings(initial_scene_probe=False, min_tool_calls=1, max_turns=3)
        with ExecutionHarness([reply('Uncited first answer'), reply(calls=[call('semantic_search')]),
                               reply('Uncited second answer'), reply('Ada wrote it [aaaaaaaa].')],
                              settings=settings) as h:
            result = h.run()
            self.assertEqual(h.state.nudges, 2)
            self.assertIn('You have made 0 tool calls', h.calls[1]['messages'][-1]['content'])
            self.assertIn('You did not call a tool.', h.calls[-1]['messages'][-2]['content'])
            self.assertEqual([e['type'] for e in h.events].count('nudge'), 2)
            self.assertEqual(h.calls[-1]['purpose'], 'forced answer')
            self.assert_result(h, result, stopped='budget', turns=3, tools=1, ids=['aaaaaaaa'])

    def test_name_correction_and_progress_feedback_precede_tool_budget_handoff(self):
        settings = AgentSettings(initial_scene_probe=False, min_tool_calls=0, max_tool_calls=1)
        def dispatch(state, name, arguments):
            return {'name': 'Mikale', 'likely': 'Mikael'}, False
        with ExecutionHarness([reply(calls=[call('find_names')]), reply('Ada wrote it [aaaaaaaa].')],
                              seed=[A], settings=settings, tools=dispatch) as h:
            with patch.object(runner, '_search_progress_hint', return_value='progress feedback'):
                result = h.run()
            messages = h.calls[-1]['messages']
            self.assertEqual([m['role'] for m in messages],
                             ['system', 'user', 'assistant', 'user', 'tool', 'user', 'user'])
            self.assertIn('Name check:', messages[3]['content'])
            self.assertEqual(messages[4]['tool_call_id'], 'agent_1_1')
            self.assertEqual(messages[5]['content'], 'progress feedback')
            self.assertEqual(h.state.resolved_names, {'Mikale'})
            self.assert_result(h, result, stopped='budget', turns=1, tools=1, ids=['aaaaaaaa'])

    def test_verifier_focus_is_ordered_deduplicated_and_limited_to_six(self):
        rows = [dict(A, id=f'{i:08x}-0000') for i in range(1, 10)]
        with ExecutionHarness([reply('Ada wrote it [aaaaaaaa].'), reply('{"supported":true}')],
                              seed=[A, *rows]) as h:
            # Set focus after normalization seeds evidence and before the first model call.
            original_chat = runner._tracked_agent_chat.side_effect
            def chat(state, *args):
                state.premise_evidence = ['00000002', 'aaaaaaaa']
                state.focus = ['00000002', '00000001', *[f'{i:08x}' for i in range(3, 10)]]
                return original_chat(state, *args)
            runner._tracked_agent_chat.side_effect = chat
            h.run()
            prompt = h.calls[1]['messages'][-1]['content']
            self.assertEqual([line.split(' |')[0] for line in prompt.splitlines() if line.startswith('[E')], [
                '[E1] id=aaaaaaaa', '[E2] id=00000002', '[E3] id=00000001', '[E4] id=00000003',
                '[E5] id=00000004', '[E6] id=00000005', '[E7] id=00000006',
            ])

    def test_main_and_forced_provider_failures_propagate_without_finalization(self):
        for provider in ('ollama', 'openai'):
            for phase in ('main', 'forced'):
                with self.subTest(provider=provider, phase=phase):
                    settings = AgentSettings(provider=provider, initial_scene_probe=False,
                                             timeout_seconds=0 if phase == 'forced' else 900)
                    with ExecutionHarness([RuntimeError('provider down')], settings=settings) as h:
                        with patch.object(runner.time, 'perf_counter', side_effect=iter(range(100))):
                            with self.assertRaisesRegex(RuntimeError, 'provider down'):
                                h.run()
                        self.assertEqual(len(h.calls), 1)
                        h.finish.assert_not_called()

    def test_verifier_provider_failure_is_local_rejection_but_openai_exception(self):
        for provider in ('ollama', 'openai'):
            with self.subTest(provider=provider):
                settings = AgentSettings(provider=provider, initial_scene_probe=False, min_tool_calls=0)
                with ExecutionHarness([reply(calls=[submit(), submit('Bea read it [bbbbbbbb].', ('bbbbbbbb',))]),
                                       RuntimeError('verifier down'), reply('{"supported":true}')],
                                      settings=settings, seed=[A, B]) as h:
                    if provider == 'openai':
                        with self.assertRaisesRegex(RuntimeError, 'verifier down'):
                            h.run()
                        h.finish.assert_not_called()
                    else:
                        result = h.run()
                        self.assertEqual(h.events[2], {'type': 'verify', 'supported': False,
                                                       'reason': 'verifier failed: RuntimeError'})
                        self.assert_result(h, result, stopped='submit', turns=1, tools=2, ids=['bbbbbbbb'])


if __name__ == '__main__':
    unittest.main()
