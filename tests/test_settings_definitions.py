"""Settings centralization: units, released resolution, exact requests and provenance."""
from copy import deepcopy
from dataclasses import asdict, fields, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.agent.state import AgentSettings as LegacyImport
from app.agent.instructions import instruction_fingerprint
from app.agent.protocol import _clip
from app.answering.cache_identity import answer_cache_identity
from app.cache import answers
from app.context.conversation import _compact
from app.experiments.metadata import _fingerprints
from app.pipelines.catalog import load_catalog
from app.pipelines.resolver import resolve
from app.settings_definitions import AgentSettings, RuntimeLimits, runtime_limits, runtime_settings_manifest
from app.settings_reference import REFERENCE, render_reference
from scripts.capture_agent_request_contract import request_contract


class SettingsDefinitions(unittest.TestCase):
    def test_legacy_import_defaults_and_definitions_are_complete(self):
        self.assertIs(LegacyImport, AgentSettings)
        fixture = json.loads((Path(__file__).parent / 'fixtures/v2_16_contract.json').read_text())
        current = AgentSettings()
        self.assertEqual(asdict(current), {name: fixture['agent'][name] for name in asdict(current)})
        for cls in (AgentSettings, RuntimeLimits):
            for item in fields(cls):
                with self.subTest(cls=cls.__name__, name=item.name):
                    definition = item.metadata['definition']
                    self.assertTrue(definition.unit and definition.explanation)
                    self.assertTrue(Path(definition.source).is_file())
        self.assertEqual(current.with_model('other').model, 'other')
        self.assertEqual(current.model, fixture['agent']['model'])
        self.assertEqual(runtime_settings_manifest(), {
            'nudge_limit': 2, 'compaction_recent_tools': 6, 'compaction_chars': 22000,
            'compaction_ids': 8, 'tool_result_chars': 9000, 'http_connect_seconds': 10,
            'ollama_read_seconds': 900, 'openai_chat_read_seconds': 180,
            'openai_responses_read_seconds': 300,
        })

    def test_validation_rejects_wrong_types_ranges_and_nonfinite_time(self):
        invalid = [dict(max_turns=True), dict(max_tool_calls=-1), dict(min_tool_calls=1.5),
                   dict(timeout_seconds=float('inf')), dict(timeout_seconds=float('nan')),
                   dict(timeout_seconds=True), dict(context_length=0), dict(num_predict=False),
                   dict(model=' '), dict(provider='other'), dict(think=1), dict(snippet_chars=-1),
                   dict(scene_candidate_count=101), dict(initial_scene_probe='yes'),
                   dict(reasoning_effort='extreme'), dict(premise_early_stop=0)]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                AgentSettings(**values)
        for values in (dict(compaction_recent_tools=0), dict(tool_result_chars=-1),
                       dict(compaction_chars=True), dict(http_connect_seconds=0)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                RuntimeLimits(**values)
        # Zero budgets still allow the current immediate budget-handoff contract.
        AgentSettings(max_turns=0, max_tool_calls=0, min_tool_calls=0, timeout_seconds=0)

    def test_catalog_and_omitted_released_setting_override_moving_defaults(self):
        actual = AgentSettings
        def moving_defaults(**values):
            return actual(**{'max_turns': 77, 'reasoning_effort': 'high', **values})
        with patch('app.pipelines.resolver.AgentSettings', side_effect=moving_defaults):
            current = resolve()
        self.assertEqual(current.agent_settings.max_turns, load_catalog().get()['agent']['max_turns'])
        self.assertEqual(current.agent_settings.reasoning_effort, 'none')
        overridden = resolve(overrides={'agent_provider': 'openai', 'agent_reasoning_effort': 'high'})
        self.assertEqual(overridden.agent_settings.reasoning_effort, 'high')
        self.assertEqual(overridden.agent_settings.model, 'gpt-6-luna')

    def test_resolver_uses_shared_validation_without_new_override_surface(self):
        for values in ({'agent_context_length': True}, {'scene_candidate_count': 101},
                       {'agent_think': 1}, {'automatic_scene_search': 'yes'},
                       {'premise_early_stop': 1}, {'nudge_limit': 3}, {'compaction_chars': 123}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                resolve(overrides=values)

    def test_model_requests_are_byte_identical_to_step2_checkout(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/v2_16_request_contract.json').read_text())
        self.assertEqual(request_contract(), fixture)
        self.assertEqual(len(fixture), 6)
        self.assertEqual({r['compacted_results'] for k, r in fixture.items() if k.endswith('True')}, {4})
        self.assertEqual({r['compacted_results'] for k, r in fixture.items() if k.endswith('False')}, {0})

    def test_compaction_character_boundary_recent_messages_and_id_limit(self):
        ids = ', '.join(json.dumps({'id': f'{i:08x}'}) for i in range(10))
        messages = [{'role': 'tool', 'tool_call_id': f'call{i}', 'content': ids} for i in range(7)]
        total = sum(len(m['content']) for m in messages)
        original = deepcopy(messages)
        _compact(messages, budget=total)
        self.assertEqual(messages, original)  # exact threshold does not compact
        _compact(messages, budget=total - 1)
        self.assertEqual(messages[1:], original[1:])
        self.assertEqual(messages[0]['tool_call_id'], 'call0')
        self.assertEqual(json.loads(messages[0]['content'])['ids'], [f'{i:08x}' for i in range(8)])
        self.assertEqual(len(_clip('x' * 10000)), runtime_limits().tool_result_chars + 1)
        self.assertEqual(_clip('x', limit=0), '…')
        self.assertEqual(_clip('x', limit=3), '"x"')

    def test_runtime_limits_affect_consumers_and_cache_identity_together(self):
        resolved = resolve()
        scope = answer_cache_identity('Q', resolved, resolved.index['collection'])
        changed = replace(runtime_limits(), compaction_chars=1, compaction_recent_tools=1, tool_result_chars=5)
        messages = [{'role': 'tool', 'content': json.dumps({'id': 'aaaaaaaa', 'text': 'evidence'})},
                    {'role': 'tool', 'content': 'latest evidence'}]
        with patch('app.settings_definitions.RUNTIME_LIMITS', changed):
            other = answer_cache_identity('Q', resolved, resolved.index['collection'])
            _compact(messages)
            self.assertEqual(_clip('long result'), '"long…')
        self.assertTrue(json.loads(messages[0]['content'])['compacted'])
        self.assertEqual(messages[1]['content'], 'latest evidence')
        self.assertNotEqual(scope['cache_key'], other['cache_key'])
        self.assertEqual(scope['runtime_settings'], runtime_settings_manifest())
        legacy = {key: value for key, value in scope.items() if key != 'runtime_settings'}
        self.assertFalse(answers._same_identity_ignoring_question_case(legacy, scope))

    def test_runtime_timeouts_follow_shared_limits(self):
        baseline = request_contract()
        with patch('app.settings_definitions.RUNTIME_LIMITS', replace(runtime_limits(),
                   http_connect_seconds=7, ollama_read_seconds=701,
                   openai_chat_read_seconds=702, openai_responses_read_seconds=703)):
            changed = request_contract()
        for key, value in changed.items():
            expected_read = 701 if key.startswith('ollama') else 702 if '/none/' in key else 703
            self.assertEqual(value['timeout'], [7, expected_read])
            self.assertEqual(value['payload_sha256'], baseline[key]['payload_sha256'])

    def test_effective_runtime_limits_are_recorded_in_experiment_pipeline_manifest(self):
        resolved = resolve()
        with patch('app.experiments.metadata.source_manifest', return_value={
                    'git_revision': 'fixture', 'dirty': False, 'source_fingerprint': 'source'}), \
             patch('app.experiments.metadata.corpus_paths', return_value=[]), \
             patch('app.experiments.metadata.resolve_ollama_model', return_value=SimpleNamespace(name='judge', digest='digest')):
            pipeline, _, _ = _fingerprints(resolved.config, {}, 'answer_correctness_v2', resolved)
        self.assertEqual(pipeline['agent_settings'], asdict(resolved.agent_settings))
        self.assertEqual(pipeline['runtime_settings'], runtime_settings_manifest())
        self.assertEqual(pipeline['fingerprint'], resolved.fingerprint)

    def test_generated_document_matches_and_override_example_is_explicit(self):
        self.assertEqual(REFERENCE.read_text(), render_reference())
        other = render_reference(overrides={'agent_provider': 'openai', 'agent_reasoning_effort': 'high'})
        self.assertIn('| `model` | `"qwen3.6:35b"` | `"qwen3.6:35b"` | `"gpt-6-luna"` |', other)
        self.assertIn('approximately 5,500 tokens', other)
        self.assertIn('approximately 2,250 tokens', other)
        self.assertIn('| `compaction_chars` | `22000` | `22000` | characters |', other)
        self.assertIn('released omission; resolver fallback', other)

    def test_released_instruction_and_protected_handoff_identity_are_unchanged(self):
        released = load_catalog().get()['agent']
        self.assertEqual(instruction_fingerprint(), released['instruction_fingerprint'])
        self.assertEqual(hashlib.sha256(Path('app/context/agent_final_handoff.py').read_bytes()).hexdigest(),
                         released['conversation_handoff_fingerprint'])


if __name__ == '__main__':
    unittest.main()
