"""Capture mocked SDK trees for Step 6; no live model, index or Langfuse calls.

Run from the repository root with PYTHONPATH including tests, in the app image.
"""
import json
from unittest.mock import patch

from app.agent import execution, submission
import test_agent_execution_contract as contracts
from test_graph_telemetry import Client, TelemetryHarness, attributes


def capture():
    budget = contracts.AgentSettings(initial_scene_probe=False, min_tool_calls=0, max_turns=0)
    cases = [
        ('tools-rejection', [
            contracts.reply(calls=[contracts.call('broken_tool'), contracts.call('semantic_search')]),
            contracts.reply(calls=[contracts.submit(), contracts.submit(), contracts.submit('Bea read it [bbbbbbbb].', ('bbbbbbbb',))]),
            contracts.reply('{"supported":false,"reason":"contradiction"}'), contracts.reply('{"supported":true}'),
        ], {}, None),
        ('budget-synthesis', [contracts.reply('Insufficient evidence.'), contracts.reply('Ada wrote it [aaaaaaaa].')],
         {'settings': budget, 'seed': [contracts.A]}, None),
        ('sequence-rewrite', [contracts.reply('She found evidence [aaaaaaaa].'), contracts.reply('{"supported":true}'),
                              contracts.reply('She arrived, found evidence, confronted him and escaped [bbbbbbbb].')],
         {'question': 'What happened to Ada?', 'seed': [contracts.A, contracts.B]}, None),
        ('provider-error', [RuntimeError('synthetic provider unavailable')], {}, None),
        ('telemetry-entry-outage', [contracts.reply('Ada wrote it [aaaaaaaa].'), contracts.reply('{"supported":true}')],
         {'seed': [contracts.A]}, 'enter'),
    ]
    output = {'kind': 'mocked SDK observations from actual LangGraph execution',
              'live_model_calls': 0, 'live_langfuse_calls': 0,
              'duration_policy': 'Observed monotonic timestamps; ancestor durations are inclusive, never sum them with descendants.',
              'cases': []}
    for name, replies, options, fail in cases:
        client = Client(fail)
        with patch.object(contracts, 'runner', execution), TelemetryHarness(replies, client=client, **options) as h, \
             attributes(session_id='synthetic-question', metadata={'execution_id': 'synthetic-step6', 'dataset_item_id': name}), \
             patch.object(submission, '_coverage_hint', return_value={}):
            result, error = None, None
            try:
                result = h.run()
            except RuntimeError as exc:
                error = str(exc)
        indices = {id(span): index for index, span in enumerate(client.spans)}
        first = client.spans[0].start if client.spans else 0
        output['cases'].append({
            'name': name, 'telemetry_fault': fail, 'error': error, 'mock_provider_calls': len(h.requests),
            'result': {key: result[key] for key in ('answer', 'stopped', 'turns', 'tool_calls', 'usage')} if result else None,
            'observations': [dict(id=index, name=span.name, parent_id=indices.get(id(span.parent)),
                                  start_ns=span.start-first, end_ns=span.end-first,
                                  fields=span.values, trace_attributes=span.attributes)
                             for index, span in enumerate(client.spans)],
        })
    return output


if __name__ == '__main__':
    print(json.dumps(capture(), indent=2))
