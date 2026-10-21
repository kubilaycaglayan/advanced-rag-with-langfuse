"""Behavior and observability contracts for the intermediate Redis cache."""
from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import patch

from app import intermediate_cache


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        return True


class RecordingSpan:
    def __init__(self, name, input, metadata):
        self.name = name
        self.input = input
        self.output = None
        self.metadata = metadata
        self.updates = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def update(self, **fields):
        self.updates.append(fields)
        self.name = fields.get("name", self.name)
        self.output = fields.get("output", self.output)
        self.metadata = fields.get("metadata", self.metadata)


class IntermediateCache(TestCase):
    def setUp(self):
        self.redis = MemoryRedis()
        self.spans = []

        @contextmanager
        def observe(name, **fields):
            span = RecordingSpan(name, fields.get("input"), fields.get("metadata"))
            self.spans.append(span)
            yield span

        self.observe_patch = patch.object(intermediate_cache, "observation", side_effect=observe)
        self.observe_patch.start()
        self.addCleanup(self.observe_patch.stop)
        self.redis_patch = patch.object(intermediate_cache, "_redis_client", return_value=self.redis)
        self.redis_patch.start()
        self.addCleanup(self.redis_patch.stop)
        self.scope = {"project_id": "project-a", "corpus_id": "corpus-a",
                      "pipeline_version": "v2.8", "pipeline_fingerprint": "fingerprint-a"}

    def test_refresh_then_use_hits_and_records_inputs_outputs_and_timing(self):
        key = {"question": "Who?"}
        original = {"normalized": "Who?", "vector": [0.1, 0.2]}
        compute = lambda: original
        with intermediate_cache.use_cache("refresh", ("embedding",), self.scope):
            self.assertEqual(intermediate_cache.cache_value(
                "embedding", "encode", key, input={"text": "Who?"}, compute=compute), original)
        self.assertEqual(self.spans[-1].name, "cache refreshed: embedding")
        self.assertEqual(self.spans[-1].output, original)

        with intermediate_cache.use_cache("use", ("embedding",), self.scope):
            result = intermediate_cache.cache_value(
                "embedding", "encode", key, input={"text": "Who?"},
                compute=lambda: self.fail("cache hit must skip compute"))
        self.assertEqual(result, original)
        self.assertEqual(self.spans[-1].name, "cache hit: embedding")
        self.assertEqual(self.spans[-1].input, {"text": "Who?"})
        self.assertEqual(self.spans[-1].output, original)
        self.assertEqual(self.spans[-1].metadata["cache_status"], "hit")
        self.assertGreaterEqual(self.spans[-1].metadata["cache_saved_seconds"], 0)

    def test_bypass_computes_without_reading_or_writing(self):
        with intermediate_cache.use_cache("bypass", ("search",), self.scope):
            result = intermediate_cache.cache_value(
                "search", "dense", {"query": "Who?"}, input={"query": "Who?"},
                compute=lambda: ["result"])
        self.assertEqual(result, ["result"])
        self.assertEqual(self.redis.values, {})
        self.assertEqual(self.spans[-1].name, "cache bypassed: search")

    def test_scope_and_layer_are_part_of_cache_identity(self):
        context = intermediate_cache.CacheContext("use", ("query",), self.scope)
        key = {"operation": "rewrite", "question": "Who?"}
        original = intermediate_cache._redis_key(context, "query", key)
        variants = [
            {**self.scope, "project_id": "project-b"},
            {**self.scope, "corpus_id": "corpus-b"},
            {**self.scope, "pipeline_version": "v2.7"},
            {**self.scope, "pipeline_fingerprint": "fingerprint-b"},
        ]
        for scope in variants:
            with self.subTest(scope=scope):
                self.assertNotEqual(original, intermediate_cache._redis_key(
                    intermediate_cache.CacheContext("use", ("query",), scope), "query", key))
        self.assertNotEqual(original, intermediate_cache._redis_key(context, "embedding", key))

    def test_redis_lookup_failure_fails_open_and_still_computes(self):
        with patch.object(intermediate_cache, "_redis_client", side_effect=ConnectionError("offline")):
            with intermediate_cache.use_cache("use", ("search",), self.scope):
                result = intermediate_cache.cache_value(
                    "search", "dense", {"query": "Who?"}, input={"query": "Who?"},
                    compute=lambda: ["computed"])
        self.assertEqual(result, ["computed"])
        self.assertEqual(self.spans[-1].name, "cache unavailable: search")
        self.assertEqual(self.spans[-1].output, ["computed"])

    def test_tool_read_trace_input_includes_question_used_in_cache_key(self):
        key = {"tool": "read_passage", "question": "Who?", "passage_id": "p-1"}
        with intermediate_cache.use_cache("refresh", ("tool_read",), self.scope):
            intermediate_cache.cache_value("tool_read", "read_passage", key,
                input={"passage_id": "p-1"}, compute=lambda: {"text": "evidence"})
        self.assertEqual(self.spans[-1].input,
                         {"passage_id": "p-1", "question": "Who?"})
