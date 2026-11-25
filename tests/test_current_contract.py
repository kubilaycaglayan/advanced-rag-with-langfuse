"""Behavioral baseline captured before retiring historical pipeline code."""
import json
from pathlib import Path
from unittest import TestCase

from app.agent import SYSTEM_PROMPT, _tool_specs
from app.pipeline_resolver import resolve
from app.prompt_templates import PROMPT_TEMPLATES


class CurrentContract(TestCase):
    def test_current_defaults_and_model_visible_contract(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/v2_16_contract.json").read_text())
        current = resolve()
        self.assertEqual(current.agent_settings.__dict__, fixture["agent"])
        self.assertEqual(current.config.manifest(), fixture["settings"])
        self.assertEqual(SYSTEM_PROMPT, fixture["system_prompt"])
        self.assertEqual(_tool_specs(), fixture["tools"])
        for name, text in PROMPT_TEMPLATES.items():
            self.assertEqual(text, fixture["prompts"][name])

    def test_provider_and_supported_options(self):
        current = resolve("v2.16", {"agent_provider": "openai", "agent_reasoning_effort": "high"})
        self.assertEqual(current.agent_settings.provider, "openai")
        self.assertEqual(current.agent_settings.model, "gpt-6-luna")
        self.assertEqual(current.agent_settings.reasoning_effort, "high")
        local = resolve(overrides={"agent_model": "local-model", "agent_think": True,
                                   "agent_context_length": 32768, "automatic_scene_search": False,
                                   "premise_early_stop": True, "scene_candidate_count": 42})
        self.assertEqual(local.agent_settings.model, "local-model")
        self.assertTrue(local.agent_settings.think)
        self.assertEqual(local.agent_settings.context_length, 32768)
        self.assertFalse(local.agent_settings.initial_scene_probe)
        self.assertTrue(local.agent_settings.premise_early_stop)
        self.assertEqual(local.agent_settings.scene_candidate_count, 42)

    def test_instruction_manifest_protects_messages_and_schemas(self):
        import ast
        from unittest.mock import patch
        from app.agent import instruction_fingerprint
        baseline = instruction_fingerprint()
        with patch("app.agent.SYSTEM_PROMPT", "changed system instruction"):
            self.assertNotEqual(instruction_fingerprint(), baseline)
        with patch("app.agent._tool_specs", return_value=[]):
            self.assertNotEqual(instruction_fingerprint(), baseline)
        parse = ast.parse
        with patch("app.agent.ast.parse", side_effect=lambda source: parse(source.replace(
                "Submit a supported answer with passage IDs, or say the evidence is insufficient.",
                "Changed inline instruction."))):
            self.assertNotEqual(instruction_fingerprint(), baseline)
        with patch("app.agent.ENTITY_CARD_DRAFT_PROMPT", "unused draft changed"):
            self.assertEqual(instruction_fingerprint(), baseline)
