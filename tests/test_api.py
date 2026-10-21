"""Narrow contract check for the interactive API's Langfuse identities."""
import asyncio
import json
import tempfile
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import AskRequest, app, ask, ask_stream, experiment_status, _run_ask
from app.experiments import _fingerprints
from app.pipeline_setup import current_pipeline_setup
from app.resolved_config import ResolvedPipelineConfig


class InteractiveAskContract(TestCase):
    def test_ask_runs_without_langfuse_credentials(self):
        resolved = SimpleNamespace(version="v1", derived=False, agent_settings=None, corpus_id="millennium",
                                   version_fields={"corpus_id": "millennium", "corpus_checksum": "checksum",
                                                   "profile_id": "millennium", "profile_identity": "profile",
                                                   "prompt_identity": "prompt"})
        prepared = {"config": ResolvedPipelineConfig(), "collection": "collection", "bundle": {},
                    "prompts": {}, "pipeline_id": "pipeline-v1-12345678", "resolved": resolved}
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict("os.environ", {"LANGFUSE_ENABLED": "false", "LANGFUSE_PUBLIC_KEY": "pk-test",
                                       "LANGFUSE_SECRET_KEY": "sk-test", "EXPERIMENT_DATA_DIR": directory}), \
             patch("app.main._prepare_ask", return_value=prepared), \
             patch("app.main.run_resolved_pipeline", return_value={"answer": "A", "citations": []}), \
             patch("app.main.langfuse_enabled", return_value=False), \
             patch("app.main.get_client") as get_client:
            result = ask(AskRequest(question="Who?"))
        self.assertIsNone(result["trace_id"])
        get_client.assert_not_called()

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
        resolved = SimpleNamespace(version="v1", derived=False, agent_settings=None, corpus_id="millennium",
                                   version_fields={"corpus_id": "millennium", "corpus_checksum": "checksum",
                                                   "profile_id": "millennium", "profile_identity": "profile",
                                                   "prompt_identity": "prompt"})
        prepared = {"config": ResolvedPipelineConfig(), "collection": "collection", "bundle": {},
                    "prompts": prompts, "pipeline_id": "pipeline-v1-12345678", "resolved": resolved}
        client = SimpleNamespace(get_current_trace_id=lambda: "a" * 32)
        with patch("app.main._prepare_ask", return_value=prepared), \
             patch("app.main.trace_scope", side_effect=propagate), \
             patch("app.main.observation", side_effect=observe), \
             patch("app.main.langfuse_enabled", return_value=True), \
             patch("app.main.get_client", return_value=client), \
             patch("app.main.run_resolved_pipeline", return_value={"answer": "A [E1]", "citations": ["[E1]"],
                                                                    "pipeline_version": "v1", "pipeline_derived": False}), \
             patch.dict("os.environ", {"FRONTEND_RATE_LIMIT_ENABLED": "true"}), \
             patch("app.main.reserve_request") as reserve:
            result = ask(AskRequest(question="Who?", engine="fixed", source="frontend", session_id="ui-127-0-0-1", user_id="interactive-ui-browser", client_ip="127.0.0.1", cache_mode="bypass"))
            ask(AskRequest(question="Who?", engine="fixed", source="api", client_ip="192.0.2.12", cache_mode="bypass"))
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
        resolved = SimpleNamespace(version="v2", derived=False, corpus_id="millennium", engine="agent", config=ResolvedPipelineConfig(),
                                   agent_settings=SimpleNamespace(model="qwen3.6:35b", provider="ollama",
                                                                  initial_scene_probe=False, scene_candidate_count=20),
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
             patch("app.main.trace_scope", return_value=nullcontext()), \
            patch("app.main.langfuse_enabled", return_value=True), \
             patch("app.main.observation", return_value=nullcontext(None)), \
             patch("app.main.update_observation"), \
             patch("app.main.get_client", return_value=client), \
             patch("app.pipeline_runner.run_agent", return_value=agent_result) as agent:
            result = ask(AskRequest(question="Who?", cache_mode="bypass"))
        self.assertEqual(result["engine"], "agent")
        self.assertEqual(result["mode"], "agent")
        self.assertEqual(result["citations"], ["[E1]"])
        self.assertEqual(result["reranked"], agent_result["evidence"])
        self.assertEqual(result["trace_id"], "a" * 32)
        self.assertEqual(result["pipeline_id"], "pipeline-v2-12345678")
        self.assertEqual(result["pipeline_version"], "v2")
        agent.assert_called_once()

    def test_cache_feedback_route_records_owner_scoped_rating(self):
        with patch("app.main.answer_cache.record_feedback", return_value="promoted") as record:
            response = TestClient(app).post("/cache/feedback", json={
                "trace_id": "a" * 32, "owner_id": "interactive-ui-browser", "helpful": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved": True, "cache_status": "promoted"})
        record.assert_called_once_with(trace_id="a" * 32, owner_id="interactive-ui-browser", helpful=True)

    def test_cache_hit_uses_fresh_trace_and_streams_cached_answer(self):
        trace_metadata = []

        @contextmanager
        def trace_scope(**kwargs):
            trace_metadata.append(kwargs)
            yield

        resolved = SimpleNamespace(
            version="v2.7", derived=False, fingerprint="fingerprint", pipeline_id="pipeline-v2.7",
            corpus_id="millennium", corpus_checksum="checksum", profile_id="millennium",
            profile_identity="profile", prompt_identity="prompt", version_fields={},
            agent_settings=None, config=ResolvedPipelineConfig())
        prepared = {"config": resolved.config, "collection": "collection", "bundle": {},
                    "prompts": {}, "pipeline_id": resolved.pipeline_id, "resolved": resolved}
        client = SimpleNamespace(get_current_trace_id=lambda: "b" * 32)
        cached = {"question": "Who?", "answer": "Cached answer [E1]", "citations": ["[E1]"]}
        tokens, statuses = [], []
        with patch("app.main.trace_scope", side_effect=trace_scope), \
             patch("app.main.observation", return_value=nullcontext(None)), \
             patch("app.main.update_observation"), \
             patch("app.main.langfuse_enabled", return_value=True), \
             patch("app.main.get_client", return_value=client), \
             patch("app.main.answer_cache.lookup", return_value=(cached, "hit", "a" * 32)), \
             patch("app.main.answer_cache.mark_served") as mark_served, \
             patch("app.main.run_resolved_pipeline") as run_pipeline:
            result = _run_ask(AskRequest(question="Who?", user_id="browser-a"), prepared,
                              on_token=tokens.append, on_status=statuses.append)

        self.assertEqual(result["trace_id"], "b" * 32)
        self.assertEqual(result["cache_source_trace_id"], "a" * 32)
        self.assertEqual(result["answer_cache_status"], "hit")
        self.assertEqual(tokens, ["Cached answer [E1]"])
        self.assertEqual(statuses, ["answering"])
        self.assertEqual(trace_metadata[0]["metadata"]["answer_cache_source_trace_id"], "a" * 32)
        mark_served.assert_called_once()
        run_pipeline.assert_not_called()

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
    def test_experiment_trigger_maps_corpus_question_set_to_hosted_dataset(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "corpus.yaml").write_text(
                "id: questions\nprofile: millennium\nquestion_sets:\n"
                "  Local set:\n    path: questions.csv\n    langfuse_dataset: Hosted set\n"
                "langfuse:\n  project: questions-project\n", encoding="utf-8")
            dataset = SimpleNamespace(id="dataset-1", project_id="project-1")
            project = SimpleNamespace(id="project-1", name="questions-project")
            get_dataset = Mock(return_value=dataset)
            fake = SimpleNamespace(get_dataset=get_dataset,
                                   api=SimpleNamespace(projects=SimpleNamespace(
                                       get=lambda: SimpleNamespace(data=[project]))))
            queued = {"execution_id": "execution-1", "status": "queued"}
            with patch.dict("os.environ", {"CORPUS_ID": "questions", "CORPUS_ROOT": directory,
                                           "EXPERIMENT_TRIGGER_TOKEN": "test-token"}), \
                 patch("app.main.Langfuse", return_value=fake), \
                 patch("app.main.langfuse_enabled", return_value=True), \
                 patch("app.main.resolve", return_value=SimpleNamespace(version="v2", overrides={})), \
                 patch("app.main.submit", return_value=(queued, True)) as submit:
                response = TestClient(app).post("/experiments/run", json={"datasetName": "Local set",
                    "customPayload": json.dumps({"pipeline": "v2"})},
                    headers={"X-Experiment-Trigger-Token": "test-token"})
            self.assertEqual(response.status_code, 202, response.text)
            get_dataset.assert_called_once_with("Hosted set")
            self.assertEqual(submit.call_args.args[0]["dataset_name"], "Hosted set")

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
             patch("app.main.langfuse_enabled", return_value=True), \
             patch("app.main.submit", return_value=(row, True)) as submit:
            response = TestClient(app).post("/experiments/run", json={"datasetName": "QA.csv",
                "customPayload": json.dumps({"pipeline": "v2"})},
                headers={"X-Experiment-Trigger-Token": "test-token"})
        self.assertEqual(response.status_code, 202, response.text)
        payload = submit.call_args.args[0]
        self.assertEqual(payload["pipeline"], "v2")
        self.assertEqual(payload["settings"], {})
        self.assertEqual(payload["variant_label"], "v2")
