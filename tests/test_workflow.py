"""Regression checks for managed edits, full retrieval, and whole-session tracing."""
import asyncio
import os
import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Keep fixture spans out of the live Langfuse project the container is configured for.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app.pipeline import run_pipeline
from app.prompt_assets import ManagedJudgePrompt, load_managed_evaluators, load_prompt_bundle, PROMPT_CATALOG
from app.resolved_config import ResolvedPipelineConfig
from app.experiments import ExperimentLangfuse


class WorkflowChecks(unittest.TestCase):
    def test_full_mode_searches_original_hyde_three_alternatives_and_grammar(self):
        queries, spans = [], []
        class Qdrant:
            def collection_exists(self, name): return True
            def query_points(self, **kwargs): return SimpleNamespace(points=[])
            def scroll(self, **kwargs): return [], None
        def encode(query, **kwargs):
            queries.append(query)
            return SimpleNamespace(tolist=lambda: [0.0])
        def observe(name, **kwargs):
            spans.append(name)
            return nullcontext(None)
        with patch('app.pipeline.qdrant_client', return_value=Qdrant()), \
             patch('app.pipeline._embedder', return_value=SimpleNamespace(encode=encode)), \
             patch('app.pipeline._observe', side_effect=observe), \
             patch('app.pipeline._ollama', side_effect=['hypothetical document', 'alternative one\nalternative two\nalternative three', 'corrected question']):
            result = run_pipeline('original question', collection='test')
        self.assertEqual(queries, ['original question', 'hypothetical document', 'alternative one', 'alternative two', 'alternative three', 'corrected question'])
        self.assertEqual(result['grammar_corrected_query'], 'corrected question')
        self.assertEqual(spans.count('query embedding'), 6)
        self.assertTrue(all(f'search: literary alternative {i}' in spans for i in (1, 2, 3)))
        self.assertIn('grammar correction', spans)

    def test_prompt_bundle_disables_cache_on_every_run(self):
        calls = []
        client = SimpleNamespace(get_prompt=lambda name, **kwargs: calls.append(kwargs) or object())
        with patch('app.prompt_assets.prompt_version', return_value={'id':'p', 'version':2}):
            load_prompt_bundle(client)
            load_prompt_bundle(client)
        self.assertEqual(len(calls), 2 * len(PROMPT_CATALOG))
        self.assertTrue(all(call['cache_ttl_seconds'] == 0 for call in calls))

    def test_edited_langfuse_prompt_reaches_answer_generation(self):
        edited = [{'role': 'system', 'content': 'Edited in Langfuse'}, {'role': 'user', 'content': 'q'}]
        compiled = {}
        def compile(**variables):
            compiled.update(variables)
            return edited
        bundle = {'rag-answer': {'client': SimpleNamespace(compile=compile)}}
        point = SimpleNamespace(id='1', score=0.9, payload={'text': 'passage', 'book': 'b'})
        class Qdrant:
            def collection_exists(self, name): return True
            def query_points(self, **kwargs): return SimpleNamespace(points=[point])
            def scroll(self, **kwargs): return [], None
        sent = []
        with patch('app.pipeline.qdrant_client', return_value=Qdrant()), \
             patch('app.pipeline._embedder', return_value=SimpleNamespace(encode=lambda q, **k: SimpleNamespace(tolist=lambda: [0.0]))), \
             patch('app.pipeline._reranker', return_value=SimpleNamespace(predict=lambda pairs, **k: [1.0])), \
             patch('app.pipeline._ollama', side_effect=lambda messages, *a, **k: sent.append(messages) or 'answer [E1]'):
            run_pipeline('question', ResolvedPipelineConfig.from_mapping({'retrieval_mode': 'baseline'}),
                         collection='test', prompt_bundle=bundle)
        self.assertEqual(sent, [edited])
        self.assertEqual(compiled['question'], 'question')
        self.assertIn('[E1]', compiled['evidence'])

    def test_managed_evaluator_edits_are_accepted_and_used(self):
        rows = [{'id': name, 'name': 'millennium-' + name, 'version': 8,
                 'type': 'llm_as_judge', 'status': 'active',
                 'prompt': [{'role':'user', 'content':'Edited rubric: {{answer}}'}],
                 'variables': ['answer'], 'modelConfig': {'model':'qwen3:8b', 'provider':'ollama-local'},
                 'outputDefinition': {'dataType':'NUMERIC','minValue':0,'maxValue':1}}
                for name in ['answer_correctness_v1','citation_support_v1']]
        response = SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'data':rows})
        with patch('app.prompt_assets._api', return_value=('http://local', None)), \
             patch('app.prompt_assets.requests.get', return_value=response):
            resolved = load_managed_evaluators()
        prompt = ManagedJudgePrompt(resolved['answer_correctness_v1'])
        self.assertEqual(prompt.compile(answer='quoted {{question}}')[0]['content'], 'Edited rubric: quoted {{question}}')
        self.assertEqual(prompt.model, 'qwen3:8b')
        self.assertEqual(resolved['answer_correctness_v1']['version'], 8)

    def test_session_context_surrounds_sdk_item_root_and_evaluators(self):
        active = []
        @contextmanager
        def propagate(**kwargs):
            active.append(kwargs)
            yield
            active.pop()
        async def process(item, *args, **kwargs):
            self.assertEqual(active, [{'session_id':'qa-dataset-item', 'environment':'sdk-experiment'}])
            return 'entire SDK tree'
        client = object.__new__(ExperimentLangfuse)
        with patch('app.experiments.propagate_attributes', side_effect=propagate), \
             patch('langfuse.Langfuse._process_experiment_item', new=AsyncMock(side_effect=process)):
            self.assertEqual(asyncio.run(client._process_experiment_item(SimpleNamespace(dataset_id='dataset', id='item'))), 'entire SDK tree')
        self.assertEqual(active, [])
