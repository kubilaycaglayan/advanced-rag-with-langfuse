"""Candidate integration through real answering/API/cache/experiment boundaries.

Candidate ResolvedRuns are injected only in tests: the catalog is not registered
until Step 7, and resolve('v2.17') remains unsupported here.
"""
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from app.api.application import app
from app.api.schemas import AskRequest
from app.answering.execution import execute_question
from app.answering.interactive import _run_ask
from app.answering.cache_identity import answer_cache_identity
from app.agent import execution
from app.cache import answers, intermediate
from app.experiments import execution as experiments
from app.experiments.metadata import _fingerprints
from app.experiments.store import enqueue
from app.pipelines.execution_identity import execution_identity
from app.pipelines.resolver import resolve
from app.settings_definitions import TargetAgentSettings
from app.storage import initialize
import test_agent_execution_contract as contracts
from test_answer_cache import MemoryRedis
from test_graph_telemetry import Client


def candidate():
    base = resolve()
    settings = TargetAgentSettings(**{key: value for key, value in asdict(base.agent_settings).items() if key != 'premise_early_stop'})
    return replace(base, version='v2.17', status='candidate', pipeline_id='candidate-v2.17-test',
                   fingerprint='synthetic-candidate', agent_settings=replace(settings, min_tool_calls=0, initial_scene_probe=False),
                   execution_backend='langgraph')


def prepared(resolved):
    return {'resolved': resolved, 'config': resolved.config, 'pipeline_id': resolved.pipeline_id,
            'collection': resolved.index['collection']}


class GraphIntegration(unittest.TestCase):
    def harness(self, replies=None, **kwargs):
        replacement = patch.object(contracts, 'runner', execution)
        replacement.start()
        self.addCleanup(replacement.stop)
        return contracts.ExecutionHarness(replies or [contracts.reply('Ada wrote it [aaaaaaaa].'),
                                                      contracts.reply('{"supported":true}')], seed=[contracts.A], **kwargs)

    def test_answering_dispatch_streams_same_result_contract_without_registering_candidate(self):
        resolved = candidate()
        tokens, statuses = [], []
        with self.harness() as h, patch('app.answering.execution.time.sleep'):
            result = execute_question('Q', resolved, resolved.index['collection'], on_token=tokens.append, on_status=statuses.append)
        self.assertEqual(result['answer'], 'Ada wrote it [E1].')
        self.assertEqual(result['citations'], ['[E1]'])
        self.assertEqual(''.join(tokens), result['answer'])
        self.assertEqual(statuses, ['thinking', 'answering'])
        self.assertEqual(result['pipeline_version'], 'v2.17')
        self.assertEqual(result['pipeline_id'], resolved.pipeline_id)
        self.assertEqual(result['evidence'], '[E1] Ada wrote the report.')
        self.assertEqual(result['agent_stopped'], 'content')
        self.assertEqual(h.state.route, 'done')
        self.assertEqual(resolve().version, 'v2.16')
        with self.assertRaisesRegex(ValueError, 'unknown pipeline'):
            resolve('v2.17')

    def test_no_graph_can_masquerade_as_v2_16_or_legacy_execution(self):
        resolved = candidate()
        for bad in (replace(resolved, version='v2.16'), replace(resolved, execution_backend='legacy')):
            with self.subTest(bad=bad.version), self.assertRaises(ValueError):
                execute_question('Q', bad, bad.index['collection'])

    def test_http_ask_and_stream_output_run_actual_graph(self):
        resolved = candidate()
        for path in ('/ask', '/ask/stream'):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory, self.harness() as h, \
                 patch.dict('os.environ', {'EXPERIMENT_DATA_DIR': directory}), \
                 patch('app.api.questions._prepare_ask', return_value=prepared(resolved)), \
                 patch('app.answering.interactive.langfuse_enabled', return_value=False), \
                 patch('app.answering.interactive.langfuse_tracing_required', return_value=False), \
                 patch('app.answering.execution.time.sleep'):
                response = TestClient(app).post(path, json={'question': 'Q', 'cache_mode': 'bypass'})
                self.assertEqual(response.status_code, 200, response.text)
                if path.endswith('stream'):
                    events = [json.loads(line) for line in response.text.splitlines()]
                    result = next(event['result'] for event in events if event['type'] == 'done')
                    self.assertEqual(''.join(e['text'] for e in events if e['type'] == 'token'), result['answer'])
                else:
                    result = response.json()
                self.assertEqual(result['answer'], 'Ada wrote it [E1].')
                self.assertEqual(result['pipeline_version'], 'v2.17')
                self.assertEqual(result['answer_cache_status'], 'bypassed')
                self.assertEqual(h.state.route, 'done')

    def test_streaming_graph_observations_keep_trace_context_across_worker_thread(self):
        from app import observability
        from test_graph_telemetry import TelemetryHarness, attributes
        resolved = candidate()
        client = Client()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(contracts, 'runner', execution), \
             TelemetryHarness([contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}')],
                              client=client, seed=[contracts.A]) as h, \
             patch.dict('os.environ', {'EXPERIMENT_DATA_DIR': directory}), \
             patch('app.api.questions._prepare_ask', return_value=prepared(resolved)), \
             patch('app.answering.interactive.langfuse_enabled', return_value=True), \
             patch('app.answering.interactive.langfuse_tracing_required', return_value=False), \
             patch('app.answering.interactive.get_client', return_value=client), \
             patch('langfuse.propagate_attributes', side_effect=attributes), \
             patch('app.answering.execution.time.sleep'):
            response = TestClient(app).post('/ask/stream', json={'question': 'Q', 'cache_mode': 'bypass', 'user_id': 'browser'})
            events = [json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(next(e['result']['answer'] for e in events if e['type'] == 'done'), 'Ada wrote it [E1].')
        root = next(span for span in client.spans if span.name == 'rag ask')
        agent = next(span for span in client.spans if span.name == 'agent run')
        self.assertIs(agent.parent, root)
        generations = [span for span in client.spans if span.values.get('as_type') == 'generation']
        self.assertEqual(len(generations), 2)
        for span in generations:
            self.assertEqual(span.attributes['metadata']['execution_backend'], 'langgraph')
            self.assertEqual(span.attributes['metadata']['pipeline_version'], 'v2.17')
            self.assertEqual(span.attributes['user_id'], 'browser')
            self.assertLessEqual(root.start, span.start)
            self.assertGreaterEqual(root.end, span.end)

    def test_cache_identities_include_graph_source_and_instruction_identity(self):
        resolved = candidate()
        first = answer_cache_identity('Q', resolved, 'fixture')
        old = answer_cache_identity('Q', resolve(), 'fixture')
        self.assertNotIn('execution_identity', old)
        self.assertEqual(first['execution_identity']['backend'], 'langgraph')
        with patch('app.agent.instructions.target_instruction_fingerprint', return_value='changed'):
            changed = answer_cache_identity('Q', resolved, 'fixture')
        self.assertNotEqual(first['cache_key'], changed['cache_key'])
        self.assertNotEqual(first['cache_key'], old['cache_key'])
        with patch('app.pipelines.execution_identity.source_manifest', return_value={'source_fingerprint': 'new-source'}):
            other_scope = intermediate.scope_for(resolved, 'fixture', 'project')
        self.assertEqual(other_scope['execution_identity']['source_fingerprint'], 'new-source')
        self.assertNotEqual(first['execution_identity'], other_scope['execution_identity'])

    def test_interactive_answer_cache_hit_skips_graph_and_preserves_new_trace(self):
        resolved = candidate()
        cache = MemoryRedis()
        scope = answer_cache_identity('Q', resolved, resolved.index['collection'])
        with patch.object(answers, '_redis_client', return_value=cache):
            self.assertTrue(answers.store_approved(scope, {'answer': 'Cached [E1]', 'citations': ['[E1]'], 'pipeline_version': 'v2.17'},
                                                  trace_id='source', approval_source='correctness', correctness_score=1.0))
            with patch('app.answering.interactive.langfuse_enabled', return_value=True), \
                 patch('app.answering.interactive.langfuse_tracing_required', return_value=False), \
                 patch('app.answering.interactive.get_client', return_value=Client()), \
                 patch('app.answering.interactive.trace_scope', return_value=nullcontext()), \
                 patch('app.answering.interactive.observation', return_value=nullcontext(None)), \
                 patch('app.answering.interactive.run_resolved_pipeline') as run:
                result = _run_ask(AskRequest(question='Q', user_id='test'), prepared(resolved))
                run.assert_not_called()
                self.assertEqual(result['answer'], 'Cached [E1]')
                self.assertEqual(result['trace_id'], 'a' * 32)
                self.assertEqual(result['cache_source_trace_id'], 'source')
                self.assertEqual(result['answer_cache_status'], 'hit')

    def test_graph_reads_intermediate_cache_in_invocation_context(self):
        resolved = candidate()
        cache, computations = MemoryRedis(), []
        scope = intermediate.scope_for(resolved, 'fixture', 'project')
        def dispatch(state, name, arguments):
            def compute():
                computations.append('search')
                return [contracts.A]
            rows = intermediate.cache_value('search', 'synthetic-search', {'query': 'Q'}, input={'query': 'Q'}, compute=compute)
            state.remember(rows)
            return {'hits': [{'id': 'aaaaaaaa'}]}, False
        for _ in range(2):
            with self.harness([contracts.reply(calls=[contracts.call('semantic_search')]),
                               contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}')], tools=dispatch) as h, \
                 patch.object(intermediate, '_redis_client', return_value=cache), \
                 intermediate.use_cache('use', ('search',), scope):
                result = execute_question('Q', resolved, 'fixture')
                self.assertEqual(result['answer'], 'Ada wrote it [E1].')
        self.assertEqual(computations, ['search'])

    def test_experiment_item_runs_graph_and_persists_candidate_provenance(self):
        resolved = candidate()
        item = SimpleNamespace(id='item', input={'question': 'Q'}, expected_output={'answer': 'Ada'}, metadata={})
        dataset = SimpleNamespace(id='dataset', name='QA.csv', items=[item])
        evals = {name: {'id': name, 'name': name, 'version': 1, 'model_config': {'model': 'judge'}, 'prompt': []}
                 for name in ('answer_correctness_v2', 'citation_support_v1')}
        class ExperimentClient:
            def flush(self):
                pass

            def run_experiment(self, **kwargs):
                output = kwargs['task'](item=item)
                return SimpleNamespace(dataset_run_id='run', dataset_run_url='https://example.test/run', experiment_id='experiment',
                                       item_results=[SimpleNamespace(item=item, trace_id='trace', output=output, evaluations=[])])
        with tempfile.TemporaryDirectory() as directory, self.harness() as h, ExitStack() as stack:
            stack.enter_context(patch.dict('os.environ', {'EXPERIMENT_DATA_DIR': str(Path(directory) / 'millennium')}))
            initialize()
            enqueue('candidate-test', {'pipeline': 'v2.17', 'cache_mode': 'bypass'}, None)
            for name, value in [('_client', ExperimentClient()), ('resolve', resolved),
                                ('_dataset_for', (dataset, datetime(2026, 11, 26, tzinfo=timezone.utc))),
                                ('load_managed_evaluators', evals), ('build_index', {'collection': resolved.index['collection']}),
                                ('_flush_client', {'completed': True, 'error': None}), ('_verify_trace_upload', None)]:
                stack.enter_context(patch.object(experiments, name, return_value=value))
            from test_observability_fail_open import BrokenContext
            stack.enter_context(patch('app.corpus_profiles.langfuse_enabled', return_value=True))
            stack.enter_context(patch('langfuse.propagate_attributes', return_value=BrokenContext('enter')))
            stack.enter_context(patch('app.experiments.metadata.resolve_ollama_model', return_value=SimpleNamespace(name='judge', digest='digest')))
            result = experiments.execute_execution('candidate-test')
            self.assertEqual(result['status'], 'completed', result)
            self.assertEqual(result['item_results'][0]['output']['answer'], 'Ada wrote it [E1].')
            manifest = json.loads((Path(directory) / 'millennium/executions/candidate-test/manifest.json').read_text())
            self.assertEqual(manifest['pipeline']['execution_identity']['backend'], 'langgraph')
            self.assertEqual(manifest['pipeline']['agent_settings'], asdict(resolved.agent_settings))
            self.assertEqual(h.state.route, 'done')


if __name__ == '__main__':
    unittest.main()
