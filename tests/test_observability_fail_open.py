"""Telemetry context failures must never skip work or replace provider failures."""
from contextlib import nullcontext
import unittest
from unittest.mock import Mock, patch

from app.observability import observation, trace_scope, use_client


class BrokenContext:
    def __init__(self, phase):
        self.phase = phase

    def __enter__(self):
        if self.phase == 'enter':
            raise RuntimeError('telemetry enter failed')
        return None

    def __exit__(self, *exc):
        if self.phase == 'exit':
            raise RuntimeError('telemetry exit failed')
        return True  # Even an SDK suppression request must not swallow provider errors.


class FailOpenTelemetry(unittest.TestCase):
    def contexts(self, kind, phase):
        if kind == 'observation':
            client = Mock()
            client.start_as_current_observation.return_value = BrokenContext(phase)
            return use_client(client), observation('test')
        return nullcontext(), trace_scope(metadata={'execution_id': 'test'})

    def test_context_entry_failure_still_executes_body_once(self):
        for kind in ('observation', 'scope'):
            with self.subTest(kind=kind), patch('app.corpus_profiles.langfuse_enabled', return_value=True), \
                 patch('langfuse.propagate_attributes', return_value=BrokenContext('enter')):
                owner, context = self.contexts(kind, 'enter')
                calls = []
                with owner, context:
                    calls.append('answer')
                self.assertEqual(calls, ['answer'])

    def test_provider_failure_is_never_replaced_or_suppressed_by_telemetry(self):
        for kind in ('observation', 'scope'):
            for phase in ('enter', 'exit', 'suppress'):
                with self.subTest(kind=kind, phase=phase), patch('app.corpus_profiles.langfuse_enabled', return_value=True), \
                     patch('langfuse.propagate_attributes', return_value=BrokenContext(phase)):
                    owner, context = self.contexts(kind, phase)
                    failure = RuntimeError('provider unavailable')
                    with self.assertRaises(RuntimeError) as caught:
                        with owner, context:
                            raise failure
                    self.assertIs(caught.exception, failure)

    def test_disabled_scope_preserves_provider_error(self):
        failure = RuntimeError('provider unavailable')
        with patch('app.corpus_profiles.langfuse_enabled', return_value=False):
            with self.assertRaises(RuntimeError) as caught:
                with trace_scope():
                    raise failure
        self.assertIs(caught.exception, failure)

    def test_context_exit_failure_preserves_successful_result(self):
        for kind in ('observation', 'scope'):
            with self.subTest(kind=kind), patch('app.corpus_profiles.langfuse_enabled', return_value=True), \
                 patch('langfuse.propagate_attributes', return_value=BrokenContext('exit')):
                owner, context = self.contexts(kind, 'exit')
                result = []
                with owner, context:
                    result.append('answer')
                self.assertEqual(result, ['answer'])
