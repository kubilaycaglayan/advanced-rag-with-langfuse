"""Narrow contract check for the interactive API's Langfuse identities."""
import asyncio
import json
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import AskRequest, app, ask, ask_stream, experiment_status
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
        resolved = SimpleNamespace(version="v1", derived=False)
        prepared = {"config": ResolvedPipelineConfig(), "collection": "collection", "bundle": {},
                    "prompts": prompts, "pipeline_id": "pipeline-v1-12345678", "resolved": resolved}
        client = SimpleNamespace(get_current_trace_id=lambda: "a" * 32)
        with patch("app.main._prepare_ask", return_value=prepared), \
             patch("app.main.propagate_attributes", side_effect=propagate), \
             patch("app.main.observation", side_effect=observe), \
             patch("app.main.get_client", return_value=client), \
             patch("app.main.run_resolved_pipeline", return_value={"answer": "A [E1]", "citations": ["[E1]"],
                                                                    "pipeline_version": "v1", "pipeline_derived": False}), \
             patch.dict("os.environ", {"FRONTEND_RATE_LIMIT_ENABLED": "true"}), \
             patch("app.main.reserve_request") as reserve:
            result = ask(AskRequest(question="Who?", engine="fixed", source="frontend", session_id="ui-127-0-0-1", user_id="interactive-ui-browser", client_ip="127.0.0.1"))
            ask(AskRequest(question="Who?", engine="fixed", source="api", client_ip="192.0.2.12"))
            reserve.assert_not_called()

        self.assertEqual(result["trace_id"], "a" * 32)
        self.assertEqual(result["pipeline_id"], "pipeline-v1-12345678")
        self.assertEqual(result["pipeline_version"], "v1")
        self.assertEqual(attributes[0]["environment"], "interactive-ui")
        self.assertEqual(attributes[0]["session_id"], "ui-127-0-0-1")
        self.assertEqual(attributes[0]["user_id"], "interactive-ui-browser")
        self.assertIsNone(attributes[1]["user_id"])
        self.assertEqual(attributes[0]["metadata"]["pipeline_id"], "pipeline-v1-12345678")
        self.assertIn("pipeline:pipeline-v1-12345678", attributes[0]["tags"])
        self.assertEqual(observations[0]["metadata"], {"clientIp": "127.0.0.1"})
        self.assertIsNone(observations[1]["metadata"])

    def test_ask_defaults_to_the_agent_engine(self):
        resolved = SimpleNamespace(version="v2", derived=False, engine="agent", config=ResolvedPipelineConfig(),
                                   agent_settings=SimpleNamespace(model="qwen3.6:35b"),
                                   version_fields={"pipeline_id": "pipeline-v2-12345678", "pipeline_version": "v2",
                                                   "pipeline_derived": False})
        prepared = {"config": ResolvedPipelineConfig(), "collection": "collection", "bundle": {}, "prompts": {},
                    "pipeline_id": "pipeline-v2-12345678", "resolved": resolved}
        agent_result = {
            "question": "Who?", "answer": "A [E1]", "citations": ["E1"], "passage_ids": ["ab12cd34"],
            "evidence": [{"agent_label": "E1", "id": "ab12cd34-0000-0000-0000-000000000000", "book": "B",
                          "chapter": "C", "paragraph": 1, "page": 2, "text": "T"}],
            "trace": [{"tool": "semantic_search", "arguments": {"query": "Who?"}}], "tool_calls": 4,
            "stopped": "submit", "latency_seconds": 12.3, "model": "qwen3.6:35b"}
        client = SimpleNamespace(get_current_trace_id=lambda: "a" * 32)
        with patch("app.main._prepare_ask", return_value=prepared), \
             patch("app.main.propagate_attributes", return_value=nullcontext()), \
             patch("app.main.observation", return_value=nullcontext(None)), \
             patch("app.main.update_observation"), \
             patch("app.main.get_client", return_value=client), \
             patch("app.pipeline_runner.run_agent", return_value=agent_result) as agent:
            result = ask(AskRequest(question="Who?"))
        self.assertEqual(result["engine"], "agent")
        self.assertEqual(result["mode"], "agent")
        self.assertEqual(result["citations"], ["[E1]"])
        self.assertEqual(result["reranked"], agent_result["evidence"])
        self.assertEqual(result["trace_id"], "a" * 32)
        self.assertEqual(result["pipeline_id"], "pipeline-v2-12345678")
        self.assertEqual(result["pipeline_version"], "v2")
        agent.assert_called_once()

    def test_stream_emits_trace_status_tokens_and_the_same_done_result(self):
        prepared = {"config": ResolvedPipelineConfig(), "collection": "collection", "bundle": {}, "prompts": {}, "pipeline_id": "pipeline-123"}
        result = {"answer": "Hello world [E1]", "citations": ["[E1]"], "trace_id": "t" * 32, "pipeline_id": "pipeline-123"}
        def run(request, prepared, *, on_trace=None, on_token=None, on_status=None):
            on_trace("t" * 32)
            on_status("answering")
            on_token("Hello ")
            on_token("world [E1]")
            return result
        with patch("app.main._prepare_ask", return_value=prepared), patch("app.main._run_ask", side_effect=run):
            response = ask_stream(AskRequest(question="Who?"))
            async def collect():
                return [json.loads(chunk) async for chunk in response.body_iterator]
            events = asyncio.run(collect())
        self.assertEqual([event["type"] for event in events], ["trace", "status", "token", "token", "done"])
        self.assertEqual((events[0]["trace_id"], events[1]["status"]), ("t" * 32, "answering"))
        self.assertEqual("".join(event["text"] for event in events[2:4]), "Hello world [E1]")
        self.assertEqual(events[-1]["result"], result)

    def test_stream_reports_a_failed_pipeline_as_an_error_event(self):
        prepared = {"config": ResolvedPipelineConfig(), "collection": "collection", "bundle": {}, "prompts": {}, "pipeline_id": "pipeline-123"}
        with patch("app.main._prepare_ask", return_value=prepared), \
             patch("app.main._run_ask", side_effect=ValueError("bad question")):
            response = ask_stream(AskRequest(question="Who?"))
            async def collect():
                return [json.loads(chunk) async for chunk in response.body_iterator]
            events = asyncio.run(collect())
        self.assertEqual(events, [{"type": "error", "status": 400, "detail": "bad question"}])


class VersionPayloadContract(TestCase):
    def test_failed_execution_status_keeps_requested_version(self):
        row = {"result_json": json.dumps({"status": "failed", "error": "prompt missing"}),
               "payload_json": json.dumps({"pipeline": "v1", "settings": {"passage_chars": 600}}),
               "status": "failed", "created_at": None, "updated_at": None,
               "started_at": None, "finished_at": None, "error": "prompt missing"}
        with patch("app.main.get_execution", return_value=row):
            status = experiment_status("execution-1")
        self.assertEqual(status["pipeline_version"], "v1")
        self.assertTrue(status["pipeline_derived"])

    def test_ask_rejects_unknown_or_unused_settings_before_execution(self):
        slot = SimpleNamespace(close=lambda: None)
        with patch("app.main._reserve_ask_slot", return_value=slot):
            client = TestClient(app)
            for payload in ({"question": "Who?", "pipeline": "missing"},
                            {"question": "Who?", "pipeline": "v2", "settings": {"candidate_count": 50}},
                            {"question": "Who?", "pipeline": "v1", "settings": {"expansion_count": "three"}},
                            {"question": "Who?", "pipeline": "v1", "prompt_label": "production"},
                            {"question": "Who?", "pipeline": "v1", "collection": "wrong"}):
                with self.subTest(payload=payload):
                    self.assertEqual(client.post("/ask", json=payload).status_code, 400)

    def test_experiment_rejects_invalid_version_before_queueing(self):
        with patch.dict("os.environ", {"EXPERIMENT_TRIGGER_TOKEN": "test-token"}):
            client = TestClient(app)
            headers = {"X-Experiment-Trigger-Token": "test-token"}
            for payload in ({"pipeline": "missing"},
                            {"pipeline": "v1", "config": {}, "settings": {}},
                            {"pipeline": "v1", "prompt_label": "production"}):
                with self.subTest(payload=payload):
                    response = client.post("/experiments/run", json={"customPayload": payload}, headers=headers)
                    self.assertEqual(response.status_code, 400, response.text)

    def test_langfuse_remote_payload_selects_v2_before_queueing(self):
        dataset = SimpleNamespace(id="dataset-1", project_id="project-1")
        project = SimpleNamespace(id="project-1", name="millenium")
        fake = SimpleNamespace(get_dataset=lambda name: dataset,
                               api=SimpleNamespace(projects=SimpleNamespace(get=lambda: SimpleNamespace(data=[project]))))
        row = {"execution_id": "execution-1", "status": "queued"}
        with patch.dict("os.environ", {"EXPERIMENT_TRIGGER_TOKEN": "test-token"}), \
             patch("app.main.Langfuse", return_value=fake), \
             patch("app.main.submit", return_value=(row, True)) as submit:
            response = TestClient(app).post("/experiments/run", json={"datasetName": "QA.csv",
                "customPayload": json.dumps({"pipeline": "v2"})},
                headers={"X-Experiment-Trigger-Token": "test-token"})
        self.assertEqual(response.status_code, 202, response.text)
        payload = submit.call_args.args[0]
        self.assertEqual(payload["pipeline"], "v2")
        self.assertEqual(payload["settings"], {})
        self.assertEqual(payload["variant_label"], "v2")
