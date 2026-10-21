"""Approval, identity and invalidation rules for exact-answer caching."""
import fnmatch
from unittest import TestCase
from unittest.mock import Mock, patch

from app import answer_cache
from app.experiments import _cached_output_with_timing


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    def delete(self, *keys):
        removed = 0
        for key in keys:
            removed += int(self.values.pop(key, None) is not None)
        return removed

    def scan_iter(self, match="*", count=None):
        return iter(key for key in list(self.values) if fnmatch.fnmatchcase(key, match))


class AnswerCache(TestCase):
    def setUp(self):
        self.redis = MemoryRedis()
        self.redis_patch = patch.object(answer_cache, "_redis_client", return_value=self.redis)
        self.redis_patch.start()
        self.addCleanup(self.redis_patch.stop)
        self.scope = answer_cache.identity(
            project_id="millenium", corpus_id="millennium", pipeline_version="v2.7",
            pipeline_fingerprint="release-fingerprint", pipeline_id="pipeline-v2.7-id",
            corpus_checksum="book-checksum", profile_id="millennium", profile_identity="profile-id",
            prompt_identity="prompt-id", collection="books-a", question="Who is Lisbeth?",
            config={"temperature": 0}, agent_settings={"model": "qwen3.6:35b"})
        self.payload = {"question": "Who is Lisbeth?", "answer": "Lisbeth Salander [E1]",
                        "citations": ["[E1]"], "reranked": [{"text": "book evidence"}],
                        "citation_support_score": 0.0}

    def test_identity_separates_project_corpus_pipeline_and_exact_question(self):
        variants = [
            {"project_id": "other"}, {"corpus_id": "other"},
            {"pipeline_version": "v2.6"}, {"question": "Who is Lisbeth? "},
            {"collection": "books-b"}, {"prompt_identity": "new-prompt"},
        ]
        for variant in variants:
            dimensions = {key: value for key, value in self.scope.items()
                          if key not in {"cache_key", "cache_format"}}
            dimensions.update(variant)
            with self.subTest(variant=variant):
                other = answer_cache.identity(**dimensions)
                self.assertNotEqual(self.scope["cache_key"], other["cache_key"])

    def test_candidate_is_unavailable_until_same_owner_thumbs_up(self):
        self.assertTrue(answer_cache.stage_candidate(self.scope, self.payload,
                                                     trace_id="a" * 32, owner_id="browser-a"))
        self.assertEqual(answer_cache.lookup(self.scope)[:2], (None, "miss"))
        with self.assertRaises(PermissionError):
            answer_cache.record_feedback(trace_id="a" * 32, owner_id="browser-b", helpful=True)
        self.assertEqual(answer_cache.record_feedback(trace_id="a" * 32,
                                                       owner_id="browser-a", helpful=False), "not_approved")
        self.assertEqual(answer_cache.lookup(self.scope)[:2], (None, "miss"))
        self.assertEqual(answer_cache.record_feedback(trace_id="a" * 32,
                                                       owner_id="browser-a", helpful=True), "promoted")
        payload, status, source_trace_id = answer_cache.lookup(self.scope)
        self.assertEqual((status, source_trace_id), ("hit", "a" * 32))
        self.assertEqual(payload["answer"], self.payload["answer"])

    def test_correctness_gate_includes_point_nine_and_ignores_citation_score(self):
        self.assertFalse(answer_cache.store_approved(self.scope, self.payload, trace_id="b" * 32,
                                                     approval_source="correctness", correctness_score=0.8999))
        self.assertEqual(answer_cache.lookup(self.scope)[:2], (None, "miss"))
        self.assertTrue(answer_cache.store_approved(self.scope, self.payload, trace_id="c" * 32,
                                                    approval_source="correctness", correctness_score=0.90))
        payload, status, source_trace_id = answer_cache.lookup(self.scope)
        self.assertEqual((status, source_trace_id), ("hit", "c" * 32))
        self.assertEqual(payload["answer"], self.payload["answer"])

    def test_thumbs_down_invalidates_only_the_answer_version_that_was_served(self):
        answer_cache.store_approved(self.scope, self.payload, trace_id="d" * 32,
                                    approval_source="correctness", correctness_score=0.99)
        answer_cache.mark_served(trace_id="e" * 32, scope=self.scope,
                                 owner_id="browser-a", source_trace_id="d" * 32)
        self.assertEqual(answer_cache.record_feedback(trace_id="e" * 32,
                                                       owner_id="browser-a", helpful=False), "invalidated")
        self.assertEqual(answer_cache.lookup(self.scope)[:2], (None, "miss"))
        replacement = {**self.payload, "answer": "A replacement answer [E1]"}
        answer_cache.store_approved(self.scope, replacement, trace_id="f" * 32,
                                    approval_source="correctness", correctness_score=0.99)
        answer_cache.mark_served(trace_id="g" * 32, scope=self.scope,
                                 owner_id="browser-a", source_trace_id="d" * 32)
        self.assertEqual(answer_cache.record_feedback(trace_id="g" * 32,
                                                       owner_id="browser-a", helpful=False), "not_approved")
        self.assertEqual(answer_cache.lookup(self.scope)[0]["answer"], replacement["answer"])

    def test_scoped_and_whole_cache_clear(self):
        answer_cache.store_approved(self.scope, self.payload, trace_id="h" * 32,
                                    approval_source="correctness", correctness_score=0.99)
        other = answer_cache.identity(
            project_id="other-project", corpus_id="millennium", pipeline_version="v2.7",
            pipeline_fingerprint="release-fingerprint", pipeline_id="pipeline-v2.7-id",
            corpus_checksum="book-checksum", profile_id="millennium", profile_identity="profile-id",
            prompt_identity="prompt-id", collection="books-a", question="Other question",
            config={"temperature": 0}, agent_settings={"model": "qwen3.6:35b"})
        answer_cache.store_approved(other, self.payload, trace_id="i" * 32,
                                    approval_source="correctness", correctness_score=0.99)
        self.assertEqual(answer_cache.clear(project_id="millenium", selected_corpus_id="millennium",
                                            pipeline_version="v2.7", question=None), 1)
        self.assertEqual(answer_cache.lookup(self.scope)[:2], (None, "miss"))
        self.assertEqual(answer_cache.lookup(other)[0]["answer"], self.payload["answer"])
        self.assertEqual(answer_cache.lookup(other)[1], "hit")
        self.assertEqual(answer_cache.clear(project_id=None, selected_corpus_id=None,
                                            pipeline_version=None, question=None, all_entries=True), 1)

    def test_lookup_fails_open_when_redis_is_unavailable(self):
        failed_client = Mock()
        failed_client.get.side_effect = ConnectionError("redis offline")
        with patch.object(answer_cache, "_redis_client", return_value=failed_client):
            self.assertEqual(answer_cache.lookup(self.scope), (None, "unavailable", None))

    def test_cached_experiment_output_records_lookup_latency(self):
        cached = {"question": "Who is Lisbeth?", "answer": "Lisbeth Salander [E1]"}
        output = _cached_output_with_timing(cached, "j" * 32, 0.00126)
        self.assertEqual(output["answer_cache_status"], "hit")
        self.assertEqual(output["cache_source_trace_id"], "j" * 32)
        self.assertEqual(output["latency_seconds"], 0.0013)
        self.assertEqual(output["cache_latency_seconds"], 0.0013)
        self.assertEqual(output["timings"]["answer_cache_lookup_seconds"], 0.0013)
