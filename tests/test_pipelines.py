"""Version catalog, resolver, and agent instrumentation contracts."""
from __future__ import annotations

import ast
import json
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.agent import instruction_fingerprint, tool_names
from app.pipeline_catalog import CATALOG, RELEASES, fingerprint, load_catalog
from app.pipeline_resolver import resolve
from app.prompt_assets import PROMPT_CATALOG, load_prompt_bundle
from app.pipeline import run_pipeline


class PipelineVersions(TestCase):
    def test_catalog_and_reference_versions(self):
        catalog = load_catalog()
        self.assertEqual(catalog.default, "v2")
        self.assertEqual(set(catalog.versions), {"v1", "v2"})
        self.assertEqual(set(catalog.releases), {"v1", "v2"})
        self.assertEqual(catalog.versions["v2"]["agent"]["tools"], tool_names())
        self.assertEqual(catalog.versions["v2"]["agent"]["instruction_fingerprint"], instruction_fingerprint())
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
        self.assertEqual(base.version, "v2")
        self.assertEqual(base.engine, "agent")
        self.assertFalse(base.derived)
        self.assertTrue(base.pipeline_id.startswith("pipeline-v2-"))
        derived = resolve("v1", {"passage_chars": 600})
        self.assertTrue(derived.derived)
        self.assertTrue(derived.pipeline_id.startswith("derived-v1-"))
        self.assertEqual(derived.config.passage_chars, 600)
        self.assertEqual(derived.prompts["rag-query-expansion"], 4)

    def test_invalid_payload_values(self):
        cases = [lambda: resolve("missing"),
                 lambda: resolve("v2", {"candidate_count": 50}),
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
        self.assertEqual(resolve(engine="agent").version, "v2")

    def test_agent_declared_steps_have_instrumentation(self):
        source = Path(__file__).resolve().parents[1] / "app" / "agent.py"
        tree = ast.parse(source.read_text())
        spans = {node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "observation"
                 and node.args and isinstance(node.args[0], ast.Constant)
                 and isinstance(node.args[0].value, str)}
        declared = {step["name"] for step in load_catalog().get("v2")["flow"]}
        self.assertTrue(declared <= spans, sorted(declared - spans))

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
