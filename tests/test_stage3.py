from __future__ import annotations

import json
import os
import queue
import tempfile
import unittest
from datetime import datetime, timezone
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
# Keep fixture spans out of the live Langfuse project the container is configured for.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
from langfuse.api import NotFoundError

from app.identity import pipeline_identity, question_label, question_session_id
from app.resolved_config import ResolvedPipelineConfig
from app.experiment_store import enqueue, get_execution, initialize, mark_interrupted, update_execution
from app.seed_dataset import _seed_dataset
from app.evaluation import FALLBACK_FACTS, _judge, _opencode_chat, answer_facts, fact_score
from app.evaluator_specs import ANSWER_CORRECTNESS_V1, ANSWER_CORRECTNESS_V2, ANSWER_CORRECTNESS_V3
from app.indexer import index_identity
from app.experiments import _flush_client, submit_retry
from app.prompt_assets import load_prompt_bundle
from app.pipeline import run_pipeline
from app.main import _custom_payload
from app.evaluation import correctness, citation_support, is_explicit_abstention
from app import experiments as experiments_module
from app.experiments import _evaluator_prompt_manifest


class FakeClient:
    def __init__(self):
        self.dataset = None
        self.items = []
        self.api = SimpleNamespace(projects=SimpleNamespace(get=lambda: SimpleNamespace(data=[SimpleNamespace(name="millenium", id="project-1")])))

    def get_dataset(self, _name):
        if self.dataset is None:
            raise NotFoundError({"message": "not found"}, {})
        return self.dataset

    def create_dataset(self, name, **_kwargs):
        self.dataset = SimpleNamespace(id="dataset-1", name=name, project_id="project-1", items=self.items)
        return self.dataset

    def create_dataset_item(self, *, id, input, expected_output, metadata, **_kwargs):
        self.items.append(SimpleNamespace(id=id, input=input, expected_output=expected_output, metadata=metadata))
        self.dataset.items = self.items


class Stage3Checks(unittest.TestCase):
    def test_langfuse_ui_string_payload_is_decoded(self):
        encoded = '{"variant_label":"stage3-ui-trigger","item_ids":["item-1"]}'
        self.assertEqual(_custom_payload({"payload": encoded}), {
            "variant_label": "stage3-ui-trigger", "item_ids": ["item-1"]
        })

    def test_langfuse_ui_payload_must_decode_to_object(self):
        from fastapi import HTTPException
        with self.assertRaisesRegex(HTTPException, "custom payload must be valid JSON"):
            _custom_payload({"payload": "not-json"})
        with self.assertRaisesRegex(HTTPException, "custom payload must be an object"):
            _custom_payload({"payload": "[]"})

    def test_langfuse_cleanup_reports_pending_queue_without_blocking(self):
        class Client:
            def __init__(self):
                scores = queue.Queue(); scores.put("pending")
                self._resources = SimpleNamespace(tracer_provider=None, _score_ingestion_queue=scores,
                                                   _media_upload_queue=queue.Queue())
                self.shutdown_called = False
            def flush(self):
                pass
            def shutdown(self):
                self.shutdown_called = True
        client = Client()
        result = _flush_client(client, timeout_seconds=0.01)
        self.assertTrue(result["completed"])
        self.assertIn("score_ingestion queue has 1 pending", result["error"])
        self.assertFalse(client.shutdown_called)

    def test_evaluator_fingerprint_uses_prompt_versions_not_labels(self):
        prompts = {
            "rag-answer": {"id": "answer", "version": 4, "label": "staging"},
            "rag-eval-answer_correctness_v1": {"id": "judge", "version": 1, "label": "staging"},
        }
        manifest = _evaluator_prompt_manifest(prompts)
        self.assertEqual(manifest, {"rag-eval-answer_correctness_v1": {"id": "judge", "version": 1}})
        prompts["rag-eval-answer_correctness_v1"]["label"] = "production"
        self.assertEqual(_evaluator_prompt_manifest(prompts), manifest)
        prompts["rag-eval-answer_correctness_v1"]["version"] = 2
        self.assertNotEqual(_evaluator_prompt_manifest(prompts), manifest)

    def test_identity_is_stable_and_changes_with_config(self):
        a = pipeline_identity(git_revision="r", dirty=True, source_fingerprint="s", resolved_config={"x": 1}, corpus_checksum="c")
        b = pipeline_identity(git_revision="r", dirty=True, source_fingerprint="s", resolved_config={"x": 1}, corpus_checksum="c")
        c = pipeline_identity(git_revision="r", dirty=True, source_fingerprint="s", resolved_config={"x": 2}, corpus_checksum="c")
        self.assertEqual(a["pipeline_id"], b["pipeline_id"])
        self.assertNotEqual(a["pipeline_id"], c["pipeline_id"])

    def test_question_sessions_are_readable_and_stable(self):
        meta = {"source_row": 2}
        self.assertEqual(question_session_id("QA.csv", "i", meta, "Did Salander and Mikael have affair?"), "QA1-did-salander-and-mikael-have-affair")
        self.assertEqual(question_session_id("QA.csv", "i", {"source_row": 36}, "What is the  standard? chemical formula for table salt?"), "QA35-what-is-the-standard-chemical-formula-for-ta")
        self.assertEqual(question_session_id("QA.csv", "i", meta, "Säpo’s unit_name"), "QA1-säpo-s-unit-name")
        self.assertEqual(question_session_id("QA.csv", "i", meta, "Q?"), question_session_id("QA.csv", "other-id", meta, "Q?"))
        self.assertEqual(question_label("QA.csv", "i", {"source_row": 2, "label": " QA 36 "}), "QA 36")
        self.assertEqual(question_label("Additional Questions", "58343746-a482", None), "AdditionalQuestions-58343746")
        self.assertEqual(question_session_id("QA.csv", "58343746-a482", {}, ""), "QA-58343746")
        self.assertLessEqual(len(question_session_id("x" * 300, "i", None, "q")), 200)

    def test_configuration_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "unknown config fields"):
            ResolvedPipelineConfig.from_mapping({"passage_char": 600})
        self.assertNotEqual(ResolvedPipelineConfig.from_mapping({"passage_chars": 600}), ResolvedPipelineConfig())

    def test_seed_is_idempotent_and_preserves_langfuse_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path, mapping_path = root / "QA.csv", root / "mapping.json"
            csv_path.write_text("Question,Answer\nQ1,A1\nQ2,A2\n", encoding="utf-8")
            client = FakeClient()
            with patch.dict(os.environ, {"DATASET_NAME": "QA.csv"}):
                first = _seed_dataset(csv_path, mapping_path, client)
                self.assertEqual(first["created"], 2)
                client.items[0].expected_output = {"answer": "edited in Langfuse"}
                second = _seed_dataset(csv_path, mapping_path, client)
            self.assertEqual(second["created"], 0)
            self.assertEqual(client.items[0].expected_output["answer"], "edited in Langfuse")

    def test_index_identity_is_isolated_by_passage_size(self):
        with tempfile.TemporaryDirectory() as directory:
            for i in range(3):
                Path(directory, f"{i}.epub").write_bytes(f"book-{i}".encode())
            with patch.dict(os.environ, {"CORPUS_DIR": directory}):
                short = index_identity(ResolvedPipelineConfig(passage_chars=600))
                default = index_identity(ResolvedPipelineConfig(passage_chars=1200))
            self.assertNotEqual(short[0], default[0])
            self.assertNotEqual(short[1], default[1])

    def test_fact_score_weights_required_facts_over_details(self):
        present, partial, missing = ({"verdict": v} for v in ("present", "partial", "missing"))
        self.assertEqual(fact_score({"R1": present, "D1": missing, "D2": missing}, 1, 2), 0.9)
        self.assertEqual(fact_score({"R1": present, "R2": partial}, 2, 0), 0.75)
        self.assertEqual(fact_score({"R1": missing, "D1": present}, 1, 1), 0.1)

    def test_answer_facts_fall_back_to_the_reference_core_answer(self):
        self.assertEqual(answer_facts({"answer": "a", "required_facts": ["f"], "supporting_details": ["d"]}), (["f"], ["d"]))
        self.assertEqual(answer_facts({"answer": "a"}), FALLBACK_FACTS)

    def test_fact_judge_requires_every_fact_verdict_and_scores_in_code(self):
        class Response:
            def __init__(self, content): self.content = content
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": self.content}}
        relabelled = '{"R1":{"quote":"x","verdict":"present"},"D9":{"quote":"","verdict":"present"},"explanation":"e"}'
        complete = ('{"R1":{"quote":"x","verdict":"present"},"D1":{"quote":"","verdict":"missing"},'
                    '"explanation":"core answer given","score":0}')
        with patch("app.evaluation.observation", return_value=nullcontext(None)), \
             patch("app.evaluation.requests.post", side_effect=[Response(relabelled), Response(complete)]) as post:
            result = _judge(ANSWER_CORRECTNESS_V2, question="q", answer="a", expected="r", facts=(["fact"], ["detail"]))
        self.assertEqual(result["score"], 0.9)
        self.assertEqual(post.call_count, 2)
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["format"]["required"], ["R1", "D1", "explanation"])
        self.assertIn("R1. fact", sent["messages"][0]["content"])

    def test_v2_correctness_reports_its_own_score_name_and_verdicts(self):
        judged = {"score": 0.9, "explanation": "ok", "latency_seconds": 0.1,
                  "verdicts": {"R1": {"quote": "x", "verdict": "present"}}}
        with patch("app.evaluation._judge", return_value=judged) as judge:
            score = correctness(input={"question": "q"}, output={"answer": "a"}, spec=ANSWER_CORRECTNESS_V2,
                                expected_output={"answer": "r", "required_facts": ["f"], "supporting_details": []})
        self.assertEqual((score["name"], score["value"]), ("answer_correctness_v2", 0.9))
        self.assertEqual(score["metadata"]["fact_verdicts"], {"R1": "present"})
        self.assertEqual(judge.call_args.kwargs["facts"], (["f"], []))

    def test_v3_correctness_uses_the_same_fact_contract(self):
        judged = {"score": 0.95, "explanation": "ok", "latency_seconds": 0.1,
                  "verdicts": {"R1": {"quote": "x", "verdict": "present"}}}
        with patch("app.evaluation._judge", return_value=judged) as judge:
            score = correctness(input={"question": "q"}, output={"answer": "a"}, spec=ANSWER_CORRECTNESS_V3,
                                expected_output={"answer": "r", "required_facts": ["f"], "supporting_details": ["d"]})
        self.assertEqual((score["name"], score["value"]), ("answer_correctness_v3", 0.95))
        self.assertEqual(judge.call_args.kwargs["facts"], (["f"], ["d"]))

    def test_opencode_judge_keeps_tools_denied_and_returns_structured_output(self):
        calls = []
        class Response:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload
        def post(url, json=None, **kwargs):
            calls.append((url, json))
            if url.endswith("/session"):
                return Response({"id": "session-1"})
            return Response({"info": {"error": None, "structured": {"score": 0.8, "explanation": "ok"}}})
        schema = {"type": "object", "properties": {"score": {"type": "number"}}, "required": ["score"]}
        with patch("app.evaluation.requests.post", side_effect=post), \
             patch("app.evaluation.requests.delete") as delete:
            raw = _opencode_chat([{"role": "system", "content": "judge"}, {"role": "user", "content": "claim"}],
                                 "opencode/deepseek-v4.1-flash-free", "low", schema)
        self.assertEqual(json.loads(raw), {"score": 0.8, "explanation": "ok"})
        session_url, session_body = calls[0]
        self.assertTrue(session_url.endswith("/session"))
        self.assertTrue(all(rule["action"] == "deny" for rule in session_body["permission"]))
        message_url, message_body = calls[1]
        self.assertIn("/session/session-1/message", message_url)
        self.assertEqual(message_body["model"], {"providerID": "opencode", "modelID": "deepseek-v4.1-flash-free"})
        self.assertEqual(message_body["variant"], "low")
        self.assertEqual(message_body["format"], {"type": "json_schema", "schema": schema})
        self.assertEqual(message_body["system"], "judge")
        delete.assert_called_once()

    def test_opencode_judge_error_is_retried_then_reported(self):
        managed = SimpleNamespace(model="opencode/deepseek-v4.1-flash-free",
                                  compile=lambda **variables: [{"role": "user", "content": "judge"}])
        with patch("app.evaluation._opencode_chat", side_effect=ValueError("provider failed")) as opencode, \
             patch("app.evaluation.observation", return_value=nullcontext(None)):
            with self.assertRaisesRegex(RuntimeError, "after one retry"):
                _judge(ANSWER_CORRECTNESS_V1, question="q", answer="a", managed_prompt=managed)
        self.assertEqual(opencode.call_count, 2)

    def test_malformed_judge_json_retries_then_validates(self):
        class Response:
            def __init__(self, content): self.content = content
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": self.content}}
        with patch("app.evaluation.observation", return_value=nullcontext(None)), \
             patch("app.evaluation.requests.post", side_effect=[Response("not json"), Response('{"score":0.75,"explanation":"partial"}')]) as post:
            result = _judge(ANSWER_CORRECTNESS_V1, question="q", answer="a", expected="r")
        self.assertEqual(result["score"], 0.75)
        self.assertEqual(post.call_count, 2)

    def test_unavailable_ollama_is_an_evaluation_error_not_a_quality_score(self):
        with patch("app.evaluation._judge", side_effect=RuntimeError("connection refused")):
            score = correctness(input={"question": "q"}, output={"answer": "a"},
                                expected_output={"answer": "reference"})
        self.assertEqual(score["name"], "answer_correctness_v1_error")
        self.assertEqual(score["value"], "error")
        self.assertEqual(score["data_type"], "CATEGORICAL")

    def test_empty_retrieval_returns_an_explicit_abstention(self):
        class EmptyQdrant:
            def collection_exists(self, _collection): return True
            def query_points(self, **_kwargs): return SimpleNamespace(points=[])
            def scroll(self, **_kwargs): return [], None
        with patch("app.pipeline.qdrant_client", return_value=EmptyQdrant()), \
             patch("app.pipeline._embedder", return_value=SimpleNamespace(encode=lambda *_args, **_kwargs: SimpleNamespace(tolist=lambda: [0.0]))), \
             patch("app.pipeline._observe", return_value=nullcontext(None)), \
             patch("app.pipeline._update"), patch("app.pipeline._ollama") as ollama:
            result = run_pipeline("q", ResolvedPipelineConfig(retrieval_mode="baseline"), collection="empty-index")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["evidence"], "")
        self.assertEqual(result["answer"], "I could not find supporting passages.")
        ollama.assert_not_called()

    def test_invalid_citation_label_cannot_earn_support_even_if_judge_would_score_it(self):
        with patch("app.evaluation.observation", return_value=nullcontext(None)), \
             patch("app.evaluation.requests.post") as post:
            score = citation_support(input={"question": "q"},
                output={"answer": "Claim [E99].", "evidence": "[E1] supporting passage"})
        self.assertEqual(score["name"], "citation_support_v1")
        self.assertEqual(score["value"], 0.0)
        self.assertIn("[E99]", score["comment"])
        self.assertEqual(score["metadata"]["validation"], "invalid_citation_label")
        post.assert_not_called()

    def test_explicit_abstention_with_null_citation_score_is_not_an_evaluation_error(self):
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {"message": {"content": json.dumps({"score": None,
                    "explanation": "No factual claims; citation score not applicable."})}}
        with patch("app.evaluation.observation", return_value=nullcontext(None)), \
             patch("app.evaluation.requests.post", return_value=Response()):
            score = citation_support(input={"question": "Who tried to shoot Mikael?"},
                output={"answer": "The evidence does not indicate who tried to shoot Mikael. None of the passages mention it.",
                        "evidence": "[E1] passage"})
        self.assertEqual(score["name"], "citation_support_v1_status")
        self.assertEqual(score["value"], "not_applicable")

    def test_abstention_detector_counts_supported_abstention_phrasings(self):
        self.assertTrue(is_explicit_abstention("I could not find supporting passages."))
        self.assertTrue(is_explicit_abstention("The evidence does not indicate who did it."))
        self.assertFalse(is_explicit_abstention("The answer is Dimension in Mathematics [E1]."))

    def test_missing_prompt_label_fails_without_fallback(self):
        class MissingPromptClient:
            def __init__(self): self.calls = []
            def get_prompt(self, name, **kwargs):
                self.calls.append((name, kwargs))
                raise NotFoundError({"message": "not found"}, {})
        client = MissingPromptClient()
        with self.assertRaises(NotFoundError):
            load_prompt_bundle(client, label="unavailable")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1]["label"], "unavailable")

    def test_queued_job_lifecycle_and_restart_marking(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"EXPERIMENT_DATA_DIR": directory}):
            initialize()
            row, created = enqueue("execution-1", {"dataset_name": "QA.csv"}, "retry-key")
            self.assertTrue(created)
            same, created_again = enqueue("execution-2", {"dataset_name": "QA.csv"}, "retry-key")
            self.assertFalse(created_again)
            self.assertEqual(same["execution_id"], row["execution_id"])
            update_execution("execution-1", status="running", started=True)
            self.assertEqual(mark_interrupted(), 1)
            self.assertEqual(get_execution("execution-1")["status"], "failed")
            with patch("app.experiments._jobs.put"):
                retry, retry_created = submit_retry("execution-1")
            self.assertTrue(retry_created)
            self.assertEqual(json.loads(retry["payload_json"])["retry_of_execution_id"], "execution-1")

    def test_item_and_telemetry_failures_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"EXPERIMENT_DATA_DIR": directory}):
            initialize()
            enqueue("execution-partial", {"dataset_name": "QA.csv", "config": {}, "correctness_evaluator": "answer_correctness_v1"}, None)
            items = [SimpleNamespace(id=f"item-{i}", input={"question": f"q{i}"},
                                     expected_output={"answer": f"a{i}"}, metadata={}) for i in (1, 2)]
            dataset = SimpleNamespace(id="dataset-1", name="QA.csv", items=items)
            managed = {
                "answer_correctness_v1": {"id": "eval-a", "name": "answer", "version": 1, "model_config": {"model": "qwen3:8b"}, "prompt": []},
                "citation_support_v1": {"id": "eval-c", "name": "citation", "version": 1, "model_config": {"model": "qwen3:8b"}, "prompt": []},
            }
            run = SimpleNamespace(
                dataset_run_id=None, dataset_run_url=None, experiment_id=None,
                item_results=[
                    SimpleNamespace(item=items[0], trace_id="trace-1", output={"error": "failed item", "answer": ""},
                                    evaluations=[{"name": "answer_correctness_v1_error", "value": "error"}]),
                    SimpleNamespace(item=items[1], trace_id="trace-2", output={"answer": "ok"},
                                    evaluations=[{"name": "answer_correctness_v1", "value": 0.5}]),
                ],
            )
            class FakeLangfuse:
                def __init__(self):
                    self._resources = SimpleNamespace(tracer_provider=None, _score_ingestion_queue=queue.Queue(),
                                                       _media_upload_queue=queue.Queue())
                def run_experiment(self, **_kwargs): return run
                def flush(self): pass
                def shutdown(self): pass
            pipeline = {"pipeline_id": "pipeline-test"}
            evaluator = {"evaluator_id": "evaluator-test", "managed_evaluators": managed}
            with patch.object(experiments_module, "_client", return_value=FakeLangfuse()), \
                 patch.object(experiments_module, "_dataset_for", return_value=(dataset, datetime(2026, 1, 1, tzinfo=timezone.utc))), \
                 patch.object(experiments_module, "load_prompt_bundle", return_value={
                     "rag-eval-answer_correctness_v1": {"client": object()},
                     "rag-eval-citation_support_v1": {"client": object()},
                 }), \
                 patch.object(experiments_module, "prompt_manifests", return_value={}), \
                 patch.object(experiments_module, "load_managed_evaluators", return_value=managed), \
                 patch.object(experiments_module, "resolve_pipeline_model_identities", side_effect=lambda config: config), \
                 patch.object(experiments_module, "build_index", return_value={"collection": "collection-test"}), \
                 patch.object(experiments_module, "_verify_trace_upload", return_value=None), \
                 patch.object(experiments_module, "_fingerprints", return_value=(pipeline, evaluator, "checksum")):
                result = experiments_module.execute_execution("execution-partial")
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(result["failed_item_count"], 1)
        self.assertEqual(result["evaluation_failure_count"], 1)
        self.assertEqual(result["telemetry_failure_count"], 2)


if __name__ == "__main__":
    unittest.main()
