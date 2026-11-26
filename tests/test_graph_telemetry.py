"""Actual graph + provider adapter with an in-memory SDK: no live telemetry/models."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import observability
from app.agent import execution, graph, submission
from app.models import agent as models
from app.models import agent_context
import test_agent_execution_contract as contracts

_current_span = ContextVar('fake_current_span', default=None)
_attributes = ContextVar('fake_attributes', default={})


@contextmanager
def attributes(**values):
    token = _attributes.set({**_attributes.get(), **values})
    try:
        yield
    finally:
        _attributes.reset(token)


class Span:
    def __init__(self, client, name, values):
        self.client, self.name, self.values = client, name, values
        self.parent = _current_span.get()
        self.attributes = deepcopy(_attributes.get())
        self.start = self.end = None

    def __enter__(self):
        if self.client.fail == 'enter':
            raise RuntimeError('telemetry entry failed')
        self.start = time.monotonic_ns()
        self.client.spans.append(self)
        self.token = _current_span.set(self)
        return self

    def __exit__(self, *exc):
        self.end = time.monotonic_ns()
        _current_span.reset(self.token)
        if self.client.fail == 'exit':
            raise RuntimeError('telemetry exit failed')
        return False

    def update(self, **values):
        if self.client.fail == 'update':
            raise RuntimeError('telemetry update failed')
        metadata = {**(self.values.get('metadata') or {}), **(values.pop('metadata', {}) or {})}
        self.values.update(deepcopy(values))
        self.values['metadata'] = metadata


class Client:
    def __init__(self, fail=None):
        self.spans, self.fail = [], fail

    def start_as_current_observation(self, *, name, **values):
        if self.fail == 'setup':
            raise RuntimeError('telemetry setup failed')
        return Span(self, name, values)

    def get_current_trace_id(self):
        return 'a' * 32


class TelemetryHarness(contracts.ExecutionHarness):
    def __init__(self, replies, *, client=None, **kwargs):
        super().__init__(replies, **kwargs)
        self.client = client or Client()
        self.requests = []

    def __enter__(self):
        super().__enter__()
        self.stack.enter_context(patch('app.corpus_profiles.langfuse_enabled', return_value=True))
        self.stack.enter_context(observability.use_client(self.client))
        for module in (execution, submission, graph, models):
            if hasattr(module, 'observation'):
                self.stack.enter_context(patch.object(module, 'observation', observability.observation))
            update_name = 'update_observation' if hasattr(module, 'update_observation') else 'update'
            self.stack.enter_context(patch.object(module, update_name, observability.update))
        for module in (execution, submission):
            self.stack.enter_context(patch.object(module, '_tracked_agent_chat', models._tracked_agent_chat))
        def post(url, **kwargs):
            self.requests.append(deepcopy(kwargs['json']))
            value = next(self.replies)
            if isinstance(value, Exception):
                raise value
            value = deepcopy(value)
            value.update(prompt_eval_count=40, eval_count=5)
            return SimpleNamespace(ok=True, raise_for_status=lambda: None, json=lambda: value)
        self.stack.enter_context(patch.object(models.requests, 'post', side_effect=post))
        return self


class GraphTelemetry(unittest.TestCase):
    def harness(self, replies, **kwargs):
        self.runner_patch = patch.object(contracts, 'runner', execution)
        self.runner_patch.start()
        self.addCleanup(self.runner_patch.stop)
        return TelemetryHarness(replies, **kwargs)

    def test_tree_actual_execution_timing_usage_and_associations(self):
        with self.harness([
            contracts.reply(calls=[contracts.call('broken_tool'), contracts.call('semantic_search')]),
            contracts.reply(calls=[contracts.submit(), contracts.submit('Bea read it [bbbbbbbb].', ('bbbbbbbb',))]),
            contracts.reply('{"supported":false,"reason":"wrong"}'), contracts.reply('{"supported":true}'),
        ]) as h, attributes(metadata={'execution_id': 'execution', 'dataset_item_id': 'item'}, session_id='question-session'):
            result = h.run()
            spans = h.client.spans
            generations = [s for s in spans if s.values.get('as_type') == 'generation']
            self.assertEqual(len(generations), 4)
            self.assertEqual(result['usage']['calls'], 4)
            self.assertEqual(result['usage']['prompt_tokens'], 160)
            self.assertEqual(result['usage']['completion_tokens'], 20)
            self.assertEqual([s.values['metadata']['purpose'] for s in generations],
                             ['tool selection and answer', 'tool selection and answer', 'submission verification', 'submission verification'])
            for span in spans:
                self.assertIsNotNone(span.start)
                self.assertGreaterEqual(span.end, span.start)
                self.assertEqual(span.attributes['metadata']['execution_id'], 'execution')
                if span.parent:
                    self.assertLessEqual(span.parent.start, span.start)
                    self.assertGreaterEqual(span.parent.end, span.end)
                if span.values.get('as_type') != 'generation':
                    self.assertNotIn('usage_details', span.values)
                    self.assertNotIn('cost_details', span.values)
            graph_span = next(s for s in spans if s.name == 'agent graph')
            self.assertEqual(graph_span.parent.name, 'agent run')
            self.assertTrue(all(s.parent is graph_span for s in spans if s.name.startswith('graph node:')))
            self.assertEqual(generations[0].parent.parent.name, 'graph node: select')
            self.assertEqual(generations[-1].parent.name, 'submission verification')
            self.assertEqual(generations[-1].parent.parent.name, 'graph node: tools')
            failed_tool = next(s for s in spans if s.name == 'tool: broken_tool')
            self.assertEqual(failed_tool.values['level'], 'ERROR')
            rejected = next(s for s in spans if s.name == 'submission verification' and not s.values['output']['supported'])
            self.assertEqual(rejected.values['level'], 'WARNING')
            self.assertEqual(graph_span.values['output']['stopped'], 'submit')

    def test_context_measurements_use_compacted_exact_request_and_preserve_evaluator_input(self):
        from app.agent.state import AgentState, AgentSettings
        from app.pipelines.config import ResolvedPipelineConfig
        state = AgentState(question='Q', collection='fixture', config=ResolvedPipelineConfig(),
                           settings=AgentSettings(), started=0)
        messages = [{'role': 'user', 'content': 'Q'}, {'role': 'user', 'content': 'PRECHECK ' + 'y' * 50000}] + [
            {'role': 'tool', 'content': json.dumps({'id': f'{i:08x}', 'text': 'x' * 4000})} for i in range(10)]
        client = Client()
        captured = {}
        def post(url, **kwargs):
            captured.update(deepcopy(kwargs['json']))
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                'message': {'content': 'answer'}, 'prompt_eval_count': 8123, 'eval_count': 7})
        with observability.use_client(client), patch('app.corpus_profiles.langfuse_enabled', return_value=True), \
             patch.object(models.requests, 'post', side_effect=post):
            models._tracked_agent_chat(state, messages, execution._tool_specs(), 'tool selection and answer')
        generation = client.spans[0]
        metadata = generation.values['metadata']
        encoded = json.dumps(captured, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        self.assertEqual(metadata['request_sha256'], hashlib.sha256(encoded.encode()).hexdigest())
        self.assertEqual(metadata['request_characters'], len(encoded))
        self.assertEqual(metadata['estimated_request_tokens'], len(encoded) / 4)
        self.assertIn('not tokenizer', metadata['token_estimate_method'])
        self.assertGreater(metadata['estimated_request_tokens'], state.settings.context_length)
        self.assertIn('y' * 50000, generation.values['input'])
        self.assertEqual(metadata['provider_prompt_tokens'], 8123)
        self.assertEqual(metadata['compacted_tool_messages'], 4)
        self.assertEqual(json.loads(generation.values['input']), captured['messages'])
        self.assertEqual(captured['messages'], messages)
        self.assertEqual(state.usage['calls'], 1)

    def test_all_provider_paths_record_prompt_usage_and_cost_once(self):
        from app.agent.state import AgentState, AgentSettings
        from app.pipelines.config import ResolvedPipelineConfig
        cases = [
            ('ollama', 'none', {'message': {'content': 'done'}, 'prompt_eval_count': 100, 'eval_count': 10}),
            ('openai', 'none', {'choices': [{'message': {'content': 'done'}}], 'usage': {
                'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110,
                'prompt_tokens_details': {'cached_tokens': 40}}}),
            ('openai', 'high', {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'done'}]}],
                                'usage': {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110,
                                          'input_tokens_details': {'cached_tokens': 40}}}),
        ]
        for provider, effort, response in cases:
            with self.subTest(provider=provider, effort=effort):
                state = AgentState(question='Q', collection='fixture', config=ResolvedPipelineConfig(),
                                   settings=AgentSettings(provider=provider, model='gpt-6-luna' if provider == 'openai' else 'local',
                                                          reasoning_effort=effort), started=0)
                client = Client()
                with observability.use_client(client), patch('app.corpus_profiles.langfuse_enabled', return_value=True), \
                     patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic-only'}), \
                     patch.object(models.requests, 'post', return_value=SimpleNamespace(
                         ok=True, raise_for_status=lambda: None, json=lambda: response)):
                    models._tracked_agent_chat(state, [{'role': 'user', 'content': 'Q'}], None, 'submission verification')
                self.assertEqual(len(client.spans), 1)
                span = client.spans[0]
                self.assertEqual(span.values['metadata']['provider_prompt_tokens'], 100)
                self.assertTrue(span.values['metadata']['provider_prompt_tokens_available'])
                self.assertEqual(span.values['metadata']['tool_schema_characters'], 0)
                self.assertEqual(state.usage['calls'], 1)
                self.assertEqual(span.values['usage_details'], {'input': 100, 'output': 10, 'total': 110})
                if provider == 'openai':
                    self.assertEqual(span.values['cost_details']['total'], state.usage['estimated_cost_usd'])
                    self.assertEqual(state.usage['estimated_cost_usd'], 0.0000114)
                    self.assertIsNone(span.values['metadata']['configured_local_context_tokens'])

    def test_budget_and_synthesis_have_distinct_nodes_and_generate_once(self):
        settings = contracts.AgentSettings(initial_scene_probe=False, min_tool_calls=0, max_turns=0)
        with self.harness([contracts.reply('Insufficient evidence.'), contracts.reply('Ada wrote it [aaaaaaaa].')],
                          settings=settings, seed=[contracts.A]) as h:
            result = h.run()
        generations = [s for s in h.client.spans if s.values.get('as_type') == 'generation']
        self.assertEqual([s.values['metadata']['purpose'] for s in generations], ['forced answer', 'answer synthesis'])
        self.assertEqual(generations[0].parent.parent.name, 'graph node: budget')
        self.assertEqual(generations[1].parent.parent.name, 'graph node: final')
        self.assertEqual(result['stopped'], 'budget+synthesis')
        self.assertEqual(len(h.requests), 2)

    def test_telemetry_outages_do_not_change_answer_usage_or_provider_failure(self):
        for fail in ('setup', 'enter', 'exit', 'update'):
            with self.subTest(fail=fail), self.harness([
                contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}')],
                client=Client(fail), seed=[contracts.A]) as h:
                result = h.run()
                self.assertEqual(result['answer'], 'Ada wrote it [E1].')
                self.assertEqual(result['usage']['calls'], 2)
                self.assertEqual(len(h.requests), 2)
            failure = RuntimeError('provider unavailable')
            with self.subTest(fail=fail, provider_error=True), self.harness([failure], client=Client(fail)) as h:
                with self.assertRaises(RuntimeError) as caught:
                    h.run()
                self.assertIs(caught.exception, failure)
                self.assertEqual(len(h.requests), 1)


if __name__ == '__main__':
    unittest.main()
