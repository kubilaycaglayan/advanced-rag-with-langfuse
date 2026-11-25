"""Version catalog, resolver, and agent instrumentation contracts."""
from __future__ import annotations

import ast
import json
import tempfile
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.agent.state import AgentSettings
from app.agent.submission import _synthesis_rows
from app.agent.instructions import instruction_fingerprint
from app.agent.runner import run_agent
from app.agent.schemas import tool_names
from app.pipelines.catalog import CATALOG, RELEASES, fingerprint, load_catalog
from app.pipelines.resolver import resolve
from app.experiments import execution as experiments_module
from app.experiments.store import enqueue
from app.storage import initialize


class PipelineVersions(TestCase):

    def test_release_fingerprint_detects_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "pipelines.md"
            releases_path = Path(directory) / "pipelines.sha256"
            catalog_path.write_text(CATALOG.read_text().replace('"expansion_count": 3', '"expansion_count": 2', 1))
            releases_path.write_text(RELEASES.read_text())
            with self.assertRaisesRegex(ValueError, "publish a new version"):
                load_catalog(catalog_path, releases_path)

    def test_default_and_derived_resolve(self):
        base = resolve()
        self.assertEqual(base.version, "v2.16")
        self.assertEqual(base.engine, "agent")
        self.assertFalse(base.derived)
        self.assertTrue(base.pipeline_id.startswith("pipeline-v2.16-"))
        derived = resolve("v2.16", {"passage_chars": 600})
        self.assertTrue(derived.derived)
        self.assertTrue(derived.pipeline_id.startswith("derived-v2.16-"))
        self.assertEqual(derived.config.passage_chars, 600)
        self.assertEqual(derived.prompts, {})

    def test_invalid_payload_values(self):
        cases = [lambda: resolve("missing"),
                 lambda: resolve("v2.16", {"candidate_count": 50}),
                 lambda: resolve("v2.16", {"corpus_checksum": "x"}),
                 lambda: resolve("v2.16", {"expansion_count": "three"}),
                 lambda: resolve("v2.16", engine="fixed"),
                 lambda: resolve("v2.16", collection="wrong")]
        for call in cases:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()

    def test_legacy_engine_alias(self):
        with self.assertRaisesRegex(ValueError, "only the agent"):
            resolve(engine="fixed")
        self.assertEqual(resolve(engine="agent").version, "v2.16")

    def test_agent_declared_steps_have_instrumentation(self):
        source = Path(__file__).resolve().parents[1] / "app"
        tree = ast.Module(body=[node for path in source.rglob("*.py")
                                for node in ast.parse(path.read_text()).body], type_ignores=[])
        spans = {node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "observation"
                 and node.args and isinstance(node.args[0], ast.Constant)
                 and isinstance(node.args[0].value, str)}
        declared = {step["name"] for step in load_catalog().get("v2.16")["flow"]}
        # Search progress is currently reported in tool results rather than a dedicated span.
        self.assertTrue(declared - {"search progress check"} <= spans, sorted(declared - spans))

    def test_agent_prechecks_nudge_and_forced_answer_emit_spans(self):
        spans = []
        def observe(name, **kwargs):
            spans.append(name)
            return nullcontext(None)
        with patch("app.agent.runner.observation", side_effect=observe), \
             patch("app.agent.runner._normalize_question", side_effect=lambda state: (state.question, [])), \
             patch("app.agent.runner._connection_precheck", return_value=None), \
             patch("app.agent.runner._true_account_precheck", return_value=None), \
             patch("app.agent.runner._sequence_precheck", return_value=None), \
             patch("app.agent.runner._moment_precheck", return_value=None), \
             patch("app.models.agent._ollama_chat", return_value={"message": {"content": "No passage found", "tool_calls": []}}):
            result = run_agent("Who?", "fixture", resolve("v2.16").config,
                               settings=AgentSettings(model="qwen3.6:35b", max_turns=1, min_tool_calls=0, initial_scene_probe=False))
        self.assertEqual(result["stopped"], "budget")
        for name in ("connection pre-check", "true account pre-check", "sequence pre-check",
                     "moment pre-check", "no tool nudge", "forced answer"):
            self.assertIn(name, spans)

    def test_query_aware_synthesis_reranking_emits_declared_span(self):
        spans = []

        @contextmanager
        def observe(name, **kwargs):
            spans.append(name)
            yield SimpleNamespace(update=lambda **fields: None)

        rows = [
            {"id": "passage-1", "text": "focused evidence"},
            {"id": "passage-2", "text": "other evidence"},
            {"id": "passage-3", "text": "third evidence"},
        ]
        state = SimpleNamespace(
            evidence={row["id"]: row for row in rows},
            order=[row["id"] for row in rows],
            focus=["passage-1"],
            question="Who?",
            retrieval_queries={},
            settings=SimpleNamespace(query_aware_reranking=True),
            config=SimpleNamespace(reranker_model=SimpleNamespace(name="reranker", revision="rev")),
        )

        class Reranker:
            def __init__(self):
                self.calls = 0

            def predict(self, pairs, **kwargs):
                self.calls += 1
                return [0.9] if self.calls == 1 else [0.8, 0.7]

        with patch("app.agent.submission.observation", side_effect=observe), \
             patch("app.agent.submission.reranker", return_value=Reranker()):
            selected = _synthesis_rows(state, limit=2)

        self.assertEqual([row["id"] for row in selected], ["passage-1", "passage-2"])
        self.assertIn("query-aware evidence reranking", spans)



    def test_dataset_execution_refreshes_cache_and_dispatches_v2_16(self):
        item = SimpleNamespace(id="item-1", input={"question": "Who?"}, expected_output={"answer": "A"}, metadata={})
        dataset = SimpleNamespace(id="dataset-1", name="QA.csv", items=[item])
        manifest = {"pipeline_id": "pipeline-v2.16-12345678", "pipeline_version": "v2.16", "pipeline_derived": False}
        evaluators = {name: {"id": name, "name": name, "version": 1,
                             "model_config": {"model": "qwen3:8b"}, "prompt": []}
                      for name in ("answer_correctness_v2", "citation_support_v1")}

        class Client:
            def flush(self):
                pass
            def run_experiment(self, **kwargs):
                output = kwargs["task"](item=item)
                return SimpleNamespace(dataset_run_id="run-1", dataset_run_url="https://example.test/run",
                                       experiment_id="experiment-1", item_results=[SimpleNamespace(
                                           item=item, trace_id="trace-1", output=output, evaluations=[])])

        cache_modes = []

        @contextmanager
        def record_cache_mode(mode, layers, scope):
            cache_modes.append((mode, tuple(layers)))
            yield

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"EXPERIMENT_DATA_DIR": str(Path(directory) / "millennium")}):
            initialize()
            enqueue("execution-v2.16", {"dataset_name": "QA.csv", "pipeline": "v2.16", "settings": {}}, None)
            with patch.object(experiments_module, "_client", return_value=Client()), \
                 patch.object(experiments_module, "_dataset_for", return_value=(dataset, datetime(2026, 10, 20, tzinfo=timezone.utc))), \
                 patch.object(experiments_module, "load_managed_evaluators", return_value=evaluators), \
                 patch.object(experiments_module, "build_index", return_value={"collection": resolve("v2.16").index["collection"]}), \
                 patch.object(experiments_module, "_fingerprints", return_value=(manifest, {"evaluator_id": "eval-1"}, "checksum")), \
                 patch.object(experiments_module, "_flush_client", return_value={"completed": True, "error": None}), \
                 patch.object(experiments_module, "_verify_trace_upload", return_value=None), \
                 patch.object(experiments_module, "propagate_attributes", return_value=nullcontext()), \
                 patch.object(experiments_module, "use_intermediate_cache", side_effect=record_cache_mode), \
                 patch.object(experiments_module.answer_cache, "lookup") as lookup, \
                 patch.object(experiments_module, "run_resolved_pipeline", return_value={"answer": "A", "citations": [], "evidence": ""}) as runner:
                result = experiments_module.execute_execution("execution-v2.16")
            recorded = json.loads((Path(directory) / "millennium" / "executions" / "execution-v2.16" / "manifest.json").read_text())
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["pipeline_version"], "v2.16")
        self.assertFalse(recorded["pipeline"]["pipeline_derived"])
        self.assertEqual(runner.call_args.args[1].engine, "agent")
        self.assertEqual(cache_modes[0][0], "refresh")
        lookup.assert_not_called()


class SupportedCatalog(TestCase):
    def test_only_current_pipeline_is_available(self):
        catalog = load_catalog()
        self.assertEqual(set(catalog.versions), {"v2.16"})
        self.assertEqual(set(catalog.releases), {"v2.16"})
        for version in ("v1", "v2", *(f"v2.{i}" for i in range(2, 16))):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "unknown pipeline"):
                resolve(version)

    def test_instruction_tampering_is_rejected(self):
        with patch("app.pipelines.resolver.instruction_fingerprint", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "agent instructions differ"):
                resolve()
