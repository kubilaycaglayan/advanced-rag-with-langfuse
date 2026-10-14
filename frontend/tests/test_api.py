"""Narrow contract check for the interactive API's Langfuse identities."""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from fastapi import HTTPException

from app.main import AskRequest, ask
from app.experiments import _fingerprints
from app.pipeline_setup import current_pipeline_setup
from app.resolved_config import ResolvedPipelineConfig


class InteractiveAskContract(TestCase):
    def test_remote_frontend_quota_rejection_is_429_with_retry_after(self):
        with patch.dict("os.environ", {"FRONTEND_RATE_LIMIT_ENABLED": "true"}), \
             patch("app.main.reserve_request", return_value=60) as reserve:
            with self.assertRaises(HTTPException) as error:
                ask(AskRequest(question="Who?", source="frontend", client_ip="198.51.100.9", production=True))
            self.assertEqual(error.exception.status_code, 429)
            self.assertEqual(error.exception.headers["Retry-After"], "60")
            reserve.assert_called_once_with("198.51.100.9")

    def test_setup_id_matches_experiment_pipeline_identity(self):
        config = ResolvedPipelineConfig()
        prompts = {"rag-answer": {"id": "prompt-1", "version": 2, "label": "production"}}
        model = SimpleNamespace(name="qwen3:8b", digest="digest")
        with patch("app.experiments.resolve_ollama_model", return_value=model), \
             patch("app.pipeline_setup.resolve_ollama_model", return_value=model):
            interactive = current_pipeline_setup(config, prompts)
            experiment, _, _ = _fingerprints(config, datetime.now(timezone.utc), prompts, {})
        self.assertEqual(interactive["pipeline_id"], experiment["pipeline_id"])

    def test_frontend_ask_returns_trace_and_pipeline_and_sets_environment(self):
        attributes = []
        observations = []

        @contextmanager
        def propagate(**kwargs):
            attributes.append(kwargs)
            yield

        def observe(*args, **kwargs):
            observations.append(kwargs)
            return nullcontext(None)

        prompts = {"rag-answer": {"id": "prompt-1", "version": 2, "label": "production"}}
        client = SimpleNamespace(get_current_trace_id=lambda: "a" * 32)
        with patch("app.main.resolve_pipeline_model_identities", side_effect=lambda config: config), \
             patch("app.main.index_identity", return_value=("collection", None, None, None)), \
             patch("app.main.validate_index"), \
             patch("app.main.Langfuse"), \
             patch("app.main.load_prompt_bundle", return_value={}), \
             patch("app.main.prompt_manifests", return_value=prompts), \
             patch("app.main.current_pipeline_setup", return_value={"pipeline_id": "pipeline-123"}), \
             patch("app.main.propagate_attributes", side_effect=propagate), \
             patch("app.main.observation", side_effect=observe), \
             patch("app.main.get_client", return_value=client), \
             patch("app.main.run_pipeline", return_value={"answer": "A [E1]", "citations": ["[E1]"]}), \
             patch.dict("os.environ", {"FRONTEND_RATE_LIMIT_ENABLED": "true"}), \
             patch("app.main.reserve_request") as reserve:
            result = ask(AskRequest(question="Who?", source="frontend", session_id="interactive-ui-browser", client_ip="127.0.0.1"))
            ask(AskRequest(question="Who?", source="api", client_ip="192.0.2.12"))
            reserve.assert_not_called()

        self.assertEqual(result["trace_id"], "a" * 32)
        self.assertEqual(result["pipeline_id"], "pipeline-123")
        self.assertEqual(attributes[0]["environment"], "interactive-ui")
        self.assertEqual(attributes[0]["session_id"], "interactive-ui-browser")
        self.assertEqual(attributes[0]["metadata"]["pipeline_id"], "pipeline-123")
        self.assertIn("pipeline:pipeline-123", attributes[0]["tags"])
        self.assertEqual(observations[0]["metadata"], {"clientIp": "127.0.0.1"})
        self.assertIsNone(observations[1]["metadata"])
