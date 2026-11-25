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
        self.assertEqual(current.agent_settings.__dict__,
                         {key: fixture["agent"][key] for key in current.agent_settings.__dict__})
        self.assertEqual(current.config.manifest(),
                         {key: fixture["settings"][key] for key in current.config.manifest()})
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
        with patch("app.agent.ENTITY_CARD_DRAFT_PROMPT", "unused draft changed", create=True):
            self.assertEqual(instruction_fingerprint(), baseline)

    def test_fixed_only_configuration_is_rejected(self):
        from app.resolved_config import ResolvedPipelineConfig
        for name in ("candidate_count", "top_k", "rrf_constant", "scene_context",
                     "entity_graph", "keyword_margin", "query_translation", "answer_thinking"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unknown config"):
                ResolvedPipelineConfig.from_mapping({name: True})

    def test_handoff_tampering_is_rejected(self):
        from unittest.mock import patch
        original = Path.read_bytes
        def read(path):
            return b"changed handoff" if path.name == "agent_final_handoff.py" else original(path)
        with patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(ValueError, "conversation handoff differs"):
                resolve()

    def test_all_budget_exits_use_conversation_handoff(self):
        from contextlib import ExitStack, nullcontext
        from dataclasses import replace
        from unittest.mock import patch
        from app.agent import run_agent
        base = resolve()
        for reason in ("timeout", "tool_budget", "turn_budget"):
            settings = replace(base.agent_settings, initial_scene_probe=False, min_tool_calls=0,
                               max_turns=1, max_tool_calls=1 if reason == "tool_budget" else 16,
                               timeout_seconds=0 if reason == "timeout" else 900)
            with self.subTest(reason=reason), ExitStack() as stack:
                for name in ("_connection_precheck", "_true_account_precheck", "_sequence_precheck",
                             "_moment_precheck", "_premise_probe"):
                    stack.enter_context(patch("app.agent." + name, return_value=None))
                stack.enter_context(patch("app.agent._normalize_question", side_effect=lambda state: (state.question, [])))
                stack.enter_context(patch("app.agent.observation", return_value=nullcontext(None)))
                stack.enter_context(patch("app.agent.update_observation"))
                stack.enter_context(patch("app.agent._run_tool", return_value=({"hits": [], "marker": "latest tool result"}, False)))
                stack.enter_context(patch("app.agent._finish", return_value={"answer": "answer"}))
                def chat(state, messages, tools, purpose):
                    if tools is None:
                        self.assertIn("Do not call tools.", messages[-1]["content"])
                        if reason != "timeout":
                            self.assertTrue(any("latest tool result" in str(message) for message in messages))
                        return {"message": {"content": "answer"}}
                    return {"message": {"tool_calls": [{"id": "call", "function": {
                        "name": "semantic_search", "arguments": {"query": "question"}}}]}}
                model = stack.enter_context(patch("app.agent._tracked_agent_chat", side_effect=chat))
                run_agent("Question?", "fixture", base.config, settings=settings)
                self.assertEqual(model.call_args.args[3], "forced answer")
                self.assertIsNone(model.call_args.args[2])

    def test_current_identity_and_source_fingerprints_track_changes(self):
        import tempfile
        from app.identity import source_manifest
        self.assertEqual(resolve().pipeline_id, resolve("v2.16").pipeline_id)
        self.assertNotEqual(resolve().pipeline_id,
                            resolve(overrides={"agent_provider": "openai"}).pipeline_id)
        self.assertNotEqual(resolve().pipeline_id,
                            resolve(overrides={"passage_chars": 600}).pipeline_id)
        with tempfile.TemporaryDirectory() as directory:
            code = Path(directory) / "app/example.py"
            code.parent.mkdir()
            code.write_text("first source")
            first = source_manifest(directory)
            code.write_text("changed source")
            second = source_manifest(directory)
        self.assertNotEqual(first["source_fingerprint"], second["source_fingerprint"])

    def test_local_transform_generation_retries_empty_output_and_records_usage(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.pipeline import _ollama
        replies = [{"message": {"content": ""}},
                   {"message": {"content": " transformed query "}, "prompt_eval_count": 8, "eval_count": 4}]
        responses = [SimpleNamespace(raise_for_status=lambda: None, json=lambda data=data: data) for data in replies]
        with patch("app.pipeline.requests.post", side_effect=responses) as post,              patch("app.pipeline._observe", return_value=nullcontext(None)),              patch("app.pipeline._update") as update:
            self.assertEqual(_ollama([{"role": "user", "content": "q"}], "local", (10, 20)), "transformed query")
        self.assertEqual([call.kwargs["json"]["options"]["num_predict"] for call in post.call_args_list], [10, 20])
        self.assertTrue(all(call.kwargs["json"]["think"] is False for call in post.call_args_list))
        self.assertEqual(update.call_args.kwargs["usage_details"], {"input": 8, "output": 4})

    def test_openai_errors_do_not_fall_back_to_local_model(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.agent import _agent_chat
        failure = SimpleNamespace(ok=False, status_code=503,
                                  json=lambda: {"error": {"message": "provider unavailable"}})
        for effort in ("none", "high"):
            settings = resolve(overrides={"agent_provider": "openai",
                                          "agent_reasoning_effort": effort}).agent_settings
            with self.subTest(effort=effort), patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}),                  patch("app.agent.requests.post", return_value=failure),                  patch("app.agent._ollama_chat") as local:
                with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                    _agent_chat([{"role": "user", "content": "Question"}], None, settings)
                local.assert_not_called()

    def test_premise_early_stop_uses_direct_evidence_without_entering_tool_loop(self):
        from contextlib import ExitStack, nullcontext
        from dataclasses import replace
        from unittest.mock import patch
        from app.agent import run_agent
        current = resolve(overrides={"premise_early_stop": True, "automatic_scene_search": False})
        row = {"id": "a1b2c3d4-0000", "text": "Harriet said, I am alive.",
               "book": "Book", "chapter": "Chapter", "paragraph": 1}
        with ExitStack() as stack:
            for name in ("_connection_precheck", "_true_account_precheck", "_sequence_precheck", "_moment_precheck"):
                stack.enter_context(patch("app.agent." + name, return_value=None))
            stack.enter_context(patch("app.agent._normalize_question", side_effect=lambda state: (state.question, [])))
            stack.enter_context(patch("app.agent._semantic_rows", return_value=[row]))
            stack.enter_context(patch("app.agent._verify_submission", return_value=(True, "supported")))
            stack.enter_context(patch("app.agent.observation", return_value=nullcontext(None)))
            stack.enter_context(patch("app.agent.update_observation"))
            model = stack.enter_context(patch("app.agent._tracked_agent_chat"))
            result = run_agent("Who killed Harriet?", "fixture", current.config, settings=current.agent_settings)
        self.assertEqual(result["stopped"], "premise_resolved")
        self.assertIn("No one killed Harriet", result["answer"])
        model.assert_not_called()

    def test_submission_verification_fails_closed(self):
        from dataclasses import replace
        from unittest.mock import patch
        from app.agent import AgentState, _verify_submission
        current = resolve()
        state = AgentState(question="Question?", collection="fixture", config=current.config,
                           settings=current.agent_settings, started=0)
        with patch("app.agent._row_index", return_value=({}, [])),              patch("app.agent._tracked_agent_chat", return_value={"message": {"content": "malformed verdict"}}):
            self.assertFalse(_verify_submission(state, "Unsupported answer", [])[0])
        with patch("app.agent._row_index", return_value=({}, [])),              patch("app.agent._tracked_agent_chat", side_effect=RuntimeError("provider unavailable")):
            self.assertFalse(_verify_submission(state, "Unsupported answer", [])[0])
            state.settings = replace(state.settings, provider="openai")
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                _verify_submission(state, "Unsupported answer", [])
