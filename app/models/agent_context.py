"""Fail-open measurements at the exact provider request boundary; no input changes."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from typing import Any

from app.observability import update

_active_request: ContextVar[Any] = ContextVar('agent_request_measurement', default=None)


@contextmanager
def measure_request(observation):
    measurements: dict[str, Any] = {}
    token = _active_request.set((observation, measurements))
    try:
        yield measurements
    finally:
        _active_request.reset(token)


def record_request(payload, messages, settings, endpoint):
    """Observe already-constructed input, after compaction and provider conversion."""
    active = _active_request.get()
    if active is None:
        return
    try:
        observation, measurements = active
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        message_input = json.dumps(messages, ensure_ascii=False)
        schemas = json.dumps(payload['tools'], ensure_ascii=False) if 'tools' in payload else ''
        estimate = len(serialized) / 4
        measurements.update({
            'request_endpoint': endpoint,
            'request_measurement_format': 'canonical JSON; sorted compact keys; ensure_ascii=False',
            'request_sha256': hashlib.sha256(serialized.encode()).hexdigest(),
            'request_characters': len(serialized), 'message_characters': len(message_input),
            'tool_schema_characters': len(schemas), 'message_count': len(messages),
            'compacted_tool_messages': sum('"compacted": true' in (m.get('content') or '')
                                           for m in messages if m.get('role') == 'tool'),
            'estimated_request_tokens': estimate,
            'token_estimate_method': 'serialized request characters / 4; not tokenizer or provider chat-template tokens',
            'requested_output_tokens': settings.num_predict,
            'configured_local_context_tokens': settings.context_length if settings.provider == 'ollama' else None,
        })
        # Preserve the message-list input contract used by faithfulness evaluators,
        # but record the actual compacted conversation, not the pre-call snapshot.
        update(observation, input=message_input, metadata=dict(measurements))
    except Exception:
        # A measurement failure cannot alter requests, retries or provider errors.
        return
