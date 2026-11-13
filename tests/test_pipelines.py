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

from app.agent import AgentSettings, _synthesis_rows, instruction_fingerprint, run_agent, tool_names
from app.pipeline_catalog import CATALOG, RELEASES, fingerprint, load_catalog
from app.pipeline_resolver import resolve
from app.prompt_assets import PROMPT_CATALOG, load_prompt_bundle
from app.pipeline import run_pipeline
from app import experiments as experiments_module
from app.experiment_store import enqueue, initialize


class PipelineVersions(TestCase):
    def test_catalog_and_reference_versions(self):
        catalog = load_catalog()
        self.assertEqual(catalog.default, "v2.15")
        self.assertEqual(set(catalog.versions), {"v1", "v2", "v2.2", "v2.3", "v2.4", "v2.5", "v2.6", "v2.7", "v2.8", "v2.9", "v2.10", "v2.11", "v2.12", "v2.13", "v2.14", "v2.15"})
        self.assertEqual(set(catalog.releases), {"v1", "v2", "v2.2", "v2.3", "v2.6", "v2.7", "v2.8", "v2.9", "v2.10", "v2.11", "v2.12", "v2.15"})
        self.assertEqual(catalog.versions["v2"]["agent"]["tools"], tool_names())
        self.assertEqual(catalog.versions["v2.7"]["agent"]["instruction_fingerprint"],
                         catalog.versions["v2.6"]["agent"]["instruction_fingerprint"])
        self.assertEqual(set(catalog.versions["v1"]["prompts"]), set(PROMPT_CATALOG))
        self.assertEqual(catalog.versions["v1"]["prompts"]["rag-query-expansion"], 4)

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
        self.assertEqual(base.version, "v2.15")
        self.assertEqual(base.engine, "agent")
        self.assertFalse(base.derived)
        self.assertTrue(base.pipeline_id.startswith("pipeline-v2.15-"))
        derived = resolve("v1", {"passage_chars": 600})
        self.assertTrue(derived.derived)
        self.assertTrue(derived.pipeline_id.startswith("derived-v1-"))
        self.assertEqual(derived.config.passage_chars, 600)
        self.assertEqual(derived.prompts["rag-query-expansion"], 4)

    def test_invalid_payload_values(self):
        cases = [lambda: resolve("missing"),
                 lambda: resolve("v2.9", {"candidate_count": 50}),
                 lambda: resolve("v1", {"corpus_checksum": "x"}),
                 lambda: resolve("v1", {"expansion_count": "three"}),
                 lambda: resolve("v1", engine="agent"),
                 lambda: resolve("v1", prompt_label="production"),
                 lambda: resolve("v1", collection="wrong")]
        for call in cases:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()

    def test_legacy_engine_alias(self):
        self.assertEqual(resolve(engine="fixed").version, "v1")
        self.assertEqual(resolve(engine="agent").version, "v2.15")

    def test_agent_declared_steps_have_instrumentation(self):
        source = Path(__file__).resolve().parents[1] / "app" / "agent.py"
        tree = ast.parse(source.read_text())
        spans = {node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "observation"
                 and node.args and isinstance(node.args[0], ast.Constant)
                 and isinstance(node.args[0].value, str)}
        declared = {step["name"] for step in load_catalog().get("v2.9")["flow"]}
        self.assertTrue(declared <= spans, sorted(declared - spans))

    def test_agent_prechecks_nudge_and_forced_answer_emit_spans(self):
        spans = []
        def observe(name, **kwargs):
            spans.append(name)
            return nullcontext(None)
        with patch("app.agent.observation", side_effect=observe), \
             patch("app.agent._normalize_question", side_effect=lambda state: (state.question, [])), \
             patch("app.agent._connection_precheck", return_value=None), \
             patch("app.agent._true_account_precheck", return_value=None), \
             patch("app.agent._sequence_precheck", return_value=None), \
             patch("app.agent._moment_precheck", return_value=None), \
             patch("app.agent._ollama_chat", return_value={"message": {"content": "No passage found", "tool_calls": []}}):
            result = run_agent("Who?", "fixture", resolve("v2.9").config,
                               settings=AgentSettings(model="qwen3.6:35b", max_turns=1, min_tool_calls=0))
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

        with patch("app.agent.observation", side_effect=observe), \
             patch("app.agent._reranker", return_value=Reranker()):
            selected = _synthesis_rows(state, limit=2)

        self.assertEqual([row["id"] for row in selected], ["passage-1", "passage-2"])
        self.assertIn("query-aware evidence reranking", spans)

    def test_fixed_flow_emits_declared_stage_order(self):
        spans: list[str] = []
        point = SimpleNamespace(id="abcd1234-0000", score=0.9,
                                payload={"text": "A supporting passage", "book": "Book", "chapter": "One", "paragraph": 1})
        qdrant = SimpleNamespace(collection_exists=lambda name: True,
                                  query_points=lambda **kwargs: SimpleNamespace(points=[point]))
        embedder = SimpleNamespace(encode=lambda *args, **kwargs: SimpleNamespace(tolist=lambda: [0.0]))
        reranker = SimpleNamespace(predict=lambda pairs, **kwargs: [3.0] * len(pairs))

        def observe(name, **kwargs):
            spans.append(name)
            return nullcontext(None)

        def ollama(messages, *args, **kwargs):
            name = kwargs.get("name", "answer generation")
            spans.append(name)
            return {"English translation generation": "LANGUAGE: English\nENGLISH: Question",
                    "hypothetical document generation": "hypothetical passage",
                    "literary query generation": "alternative one\nalternative two\nalternative three",
                    "grammar corrected query generation": "corrected question",
                    "answer generation": "Answer [E1]"}[name]

        with patch("app.pipeline.qdrant_client", return_value=qdrant), \
             patch("app.pipeline._embedder", return_value=embedder), \
             patch("app.pipeline._reranker", return_value=reranker), \
             patch("app.pipeline._observe", side_effect=observe), \
             patch("app.pipeline._ollama", side_effect=ollama), \
             patch("app.pipeline._english_share", return_value=0), \
             patch("app.pipeline._complete_names", side_effect=lambda question, collection: question), \
             patch("app.pipeline._keyword_search", return_value=[]), \
             patch("app.pipeline._context_hits", return_value=[]), \
             patch("app.pipeline._entity_name_hits", return_value=[]), \
             patch("app.pipeline._entity_matrix_hits", return_value=[]), \
             patch("app.pipeline._scene_hits", return_value=[]), \
             patch("app.pipeline._moment_scene_hits", return_value=([], "")):
            run_pipeline("Question", resolve("v1").config, collection="fixture")
        declared = [step["name"] for step in load_catalog().get("v1")["flow"]]
        observed = [name for name in spans if name in declared]
        self.assertEqual(list(dict.fromkeys(observed)), declared)

    def test_prompts_load_by_exact_version(self):
        class Prompt:
            def __init__(self, name, version):
                self.name, self.version = name, version
        class Client:
            def get_prompt(self, name, **kwargs):
                self_outer.assertEqual(kwargs["version"], pins[name])
                return Prompt(name, kwargs["version"])
        self_outer = self
        pins = load_catalog().get("v1")["prompts"]
        with patch("app.prompt_assets.prompt_version", side_effect=lambda prompt, label: {
                "id": "id", "name": prompt.name, "version": prompt.version, "label": label}):
            bundle = load_prompt_bundle(Client(), versions=pins)
        self.assertEqual(set(bundle), set(PROMPT_CATALOG))

    def test_dataset_execution_defaults_to_cache_bypass_and_dispatches_v2_9(self):
        item = SimpleNamespace(id="item-1", input={"question": "Who?"}, expected_output={"answer": "A"}, metadata={})
        dataset = SimpleNamespace(id="dataset-1", name="QA.csv", items=[item])
        manifest = {"pipeline_id": "pipeline-v2.9-12345678", "pipeline_version": "v2.9", "pipeline_derived": False}
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
            enqueue("execution-v2.9", {"dataset_name": "QA.csv", "pipeline": "v2.9", "settings": {}}, None)
            with patch.object(experiments_module, "_client", return_value=Client()), \
                 patch.object(experiments_module, "_dataset_for", return_value=(dataset, datetime(2026, 10, 20, tzinfo=timezone.utc))), \
                 patch.object(experiments_module, "load_managed_evaluators", return_value=evaluators), \
                 patch.object(experiments_module, "build_index", return_value={"collection": resolve("v2.9").index["collection"]}), \
                 patch.object(experiments_module, "_fingerprints", return_value=(manifest, {"evaluator_id": "eval-1"}, "checksum")), \
                 patch.object(experiments_module, "_flush_client", return_value={"completed": True, "error": None}), \
                 patch.object(experiments_module, "_verify_trace_upload", return_value=None), \
                 patch.object(experiments_module, "propagate_attributes", return_value=nullcontext()), \
                 patch.object(experiments_module, "use_intermediate_cache", side_effect=record_cache_mode), \
                 patch.object(experiments_module, "run_resolved_pipeline", return_value={"answer": "A", "citations": [], "evidence": ""}) as runner:
                result = experiments_module.execute_execution("execution-v2.9")
            recorded = json.loads((Path(directory) / "millennium" / "executions" / "execution-v2.9" / "manifest.json").read_text())
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["pipeline_version"], "v2.9")
        self.assertFalse(recorded["pipeline"]["pipeline_derived"])
        self.assertEqual(runner.call_args.args[1].engine, "agent")
        self.assertEqual(cache_modes[0][0], "bypass")
