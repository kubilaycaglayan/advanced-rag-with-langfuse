"""Regression checks for managed edits, full retrieval, and whole-session tracing."""
import asyncio
import json
import os
import threading
import unittest
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Keep fixture spans out of the live Langfuse project the container is configured for.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from app.retrieval.queries import transform_query
from app.prompt_assets import ManagedJudgePrompt, _evaluator_definitions, load_managed_evaluators
from app.pipelines.config import ResolvedPipelineConfig
from app.experiments import ExperimentLangfuse, pack_experiment_metadata


class WorkflowChecks(unittest.TestCase):
    def test_experiment_metadata_preserves_full_values_in_one_json_attribute(self):
        from langfuse._client.attributes import create_span_attributes

        original = {"execution_id": "execution", "pipeline_id": "pipeline", "config_prompt": "é" * 300,
                    "config_settings": {"nested": [1, 2, 3]}, "managed_eval_example": "judge@2"}
        propagated, packed = pack_experiment_metadata(original)
        self.assertEqual(propagated, {"execution_id": "execution", "pipeline_id": "pipeline"})
        self.assertEqual(json.loads(packed), original)
        attrs = create_span_attributes(metadata={"extended_json": packed})
        metadata_attrs = {key: value for key, value in attrs.items() if "metadata" in key}
        self.assertEqual(len(metadata_attrs), 1)
        self.assertEqual(json.loads(next(iter(metadata_attrs.values()))), original)




    def test_parallel_transformations_run_the_three_rewrites_together(self):
        barrier = threading.Barrier(3, timeout=5)
        def fake(messages, *args, **kwargs):
            barrier.wait()
            system = messages[0]["content"]
            if "short passage" in system:
                return "hypothetical document"
            if "Generate exactly" in system:
                return "alternative one\nalternative two\nalternative three"
            if "Correct the grammar" in system:
                return "corrected question"
            return "unexpected"
        config = ResolvedPipelineConfig.from_mapping({"parallel_transformations": True})
        with patch("app.retrieval.queries._observe", return_value=nullcontext(None)), \
             patch("app.retrieval.queries.local_generate", side_effect=fake):
            hypothetical, alternatives, corrected = transform_query("question", config)
        self.assertEqual(hypothetical, "hypothetical document")
        self.assertEqual(alternatives, ["alternative one", "alternative two", "alternative three"])
        self.assertEqual(corrected, "corrected question")

    def test_parallel_transformations_are_validated_as_a_boolean(self):
        self.assertTrue(ResolvedPipelineConfig.from_mapping({"parallel_transformations": True}).parallel_transformations)
        with self.assertRaises(ValueError):
            ResolvedPipelineConfig.from_mapping({"parallel_transformations": "yes"})



    def test_managed_evaluator_edits_are_accepted_and_used(self):
        rows = [{'id': name, 'name': 'millennium-' + name, 'version': 8,
                 'type': 'llm_as_judge', 'status': 'active',
                 'prompt': [{'role':'user', 'content':'Edited rubric: {{answer}}'}],
                 'variables': ['answer'], 'modelConfig': {'model':'qwen3:8b', 'provider':'ollama-local'},
                 'outputDefinition': {'dataType':'NUMERIC','minValue':0,'maxValue':1}}
                for name in ['answer_correctness_v1','answer_correctness_v2','answer_correctness_codex_v1','citation_support_v1']]
        rows.append({'id': 'v3', 'name': 'millennium-answer_correctness_v3', 'version': 1,
                     'type': 'llm_as_judge', 'status': 'paused', 'pausedReason': 'LLM_CONNECTION_MISSING',
                     'pausedMessage': 'no LLM connection found for the provider used by this evaluator',
                     'prompt': [{'role':'user', 'content':'Fact rubric: {{answer}}'}],
                     'variables': ['answer', 'required_facts', 'supporting_details'],
                     'modelConfig': {'model':'opencode/deepseek-v4.1-flash-free', 'provider':'opencode'},
                     'outputDefinition': {'dataType':'NUMERIC','minValue':0,'maxValue':1}})
        codex = next(row for row in rows if row['name'] == 'millennium-answer_correctness_codex_v1')
        codex.update(status='paused', pausedReason='LLM_CONNECTION_MISSING',
                     modelConfig={'model':'gpt-5.6-luna', 'provider':'codex-cli'})
        response = SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'data':rows})
        with patch('app.prompt_assets._api', return_value=('http://local', None)), \
             patch('app.prompt_assets.requests.get', return_value=response):
            resolved = load_managed_evaluators()
        prompt = ManagedJudgePrompt(resolved['answer_correctness_v1'])
        self.assertEqual(prompt.compile(answer='quoted {{question}}')[0]['content'], 'Edited rubric: quoted {{question}}')
        self.assertEqual(prompt.model, 'qwen3:8b')
        self.assertEqual(resolved['answer_correctness_v1']['version'], 8)
        self.assertEqual(resolved['answer_correctness_v3']['status'], 'paused')
        self.assertEqual(resolved['answer_correctness_v3']['paused_reason'], 'LLM_CONNECTION_MISSING')
        self.assertEqual(resolved['answer_correctness_codex_v1']['model_config']['model'], 'gpt-5.6-luna')

    def test_v3_catalog_uses_an_active_local_placeholder_for_langfuse(self):
        with patch.dict("os.environ", {"LANGFUSE_EVALUATOR_PROVIDER": "ollama-local", "EVALUATOR_MODEL": "qwen3:8b"}):
            definitions = {item["name"]: item for item in _evaluator_definitions()}
        v3 = definitions["millennium-answer_correctness_v3"]
        self.assertEqual(v3["modelConfig"], {"provider": "ollama-local", "model": "qwen3:8b"})
        self.assertIn("opencode/deepseek-v4.1-flash-free", v3["description"])

    def test_codex_catalog_keeps_active_entry_and_describes_actual_executor(self):
        with patch.dict("os.environ", {"LANGFUSE_EVALUATOR_PROVIDER": "ollama-local", "EVALUATOR_MODEL": "qwen3:8b"}):
            definitions = {item["name"]: item for item in _evaluator_definitions()}
        codex = definitions["millennium-answer_correctness_codex_v1"]
        self.assertEqual(codex["modelConfig"], {"provider": "ollama-local", "model": "qwen3:8b"})
        self.assertIn("Codex CLI gpt-5.6-luna", codex["description"])
        self.assertIn("experiment worker", codex["description"])

    def test_paused_ollama_evaluator_still_fails_preflight(self):
        rows = [{'id': name, 'name': 'millennium-' + name, 'version': 1,
                 'type': 'llm_as_judge', 'status': 'active',
                 'prompt': [{'role':'user', 'content':'Judge {{answer}}'}], 'variables': ['answer'],
                 'modelConfig': {'model':'qwen3:8b', 'provider':'ollama-local'},
                 'outputDefinition': {'dataType':'NUMERIC','minValue':0,'maxValue':1}}
                for name in ['answer_correctness_v1', 'answer_correctness_v2','answer_correctness_codex_v1','citation_support_v1']]
        rows.append({'id': 'v3', 'name': 'millennium-answer_correctness_v3', 'version': 1,
                     'type': 'llm_as_judge', 'status': 'paused', 'pausedReason': 'LLM_CONNECTION_MISSING',
                     'prompt': [{'role':'user', 'content':'Judge {{answer}}'}], 'variables': ['answer'],
                     'modelConfig': {'model':'qwen3:8b', 'provider':'ollama-local'},
                     'outputDefinition': {'dataType':'NUMERIC','minValue':0,'maxValue':1}})
        response = SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'data':rows})
        with patch('app.prompt_assets._api', return_value=('http://local', None)), \
             patch('app.prompt_assets.requests.get', return_value=response), \
             self.assertRaisesRegex(RuntimeError, 'not active'):
            load_managed_evaluators()

    def test_session_context_surrounds_sdk_item_root_and_evaluators(self):
        active = []
        @contextmanager
        def propagate(**kwargs):
            active.append(kwargs)
            yield
            active.pop()
        async def process(item, *args, **kwargs):
            self.assertEqual(active, [{'session_id':'QA1-did-salander-and-mikael-have-affair', 'tags':['question:QA1'], 'environment':'sdk-experiment'}])
            return 'entire SDK tree'
        client = object.__new__(ExperimentLangfuse)
        item = SimpleNamespace(dataset_id='dataset', dataset_name='QA.csv', id='item', metadata={'source_row': 2},
                               input={'question': 'Did Salander and Mikael have affair?'})
        with patch('app.experiments.propagate_attributes', side_effect=propagate), \
             patch('langfuse.Langfuse._process_experiment_item', new=AsyncMock(side_effect=process)):
            self.assertEqual(asyncio.run(client._process_experiment_item(item)), 'entire SDK tree')
        self.assertEqual(active, [])
