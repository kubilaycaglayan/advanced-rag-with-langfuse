"""Audit retained Step 8 artifacts without generation or baseline changes."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root / 'docs/experiments/langgraph-v2.17-step8'
fixed = json.loads((root / 'docs/experiments/langgraph-v2.17-step1/comparison-manifest.json').read_text())
questions = {q['item_id']: q for q in fixed['questions']}
rows = []
for directory in sorted(folder.glob('*-q??-a?')):
    result = json.loads((directory / 'results.json').read_text())
    manifest = json.loads((directory / 'manifest.json').read_text())
    request = json.loads((directory / 'request.json').read_text())
    trace = json.loads((directory / 'trace.json').read_text())
    assert result['status'] == 'completed', directory
    assert result['dataset_item_count'] == result['completed_item_count'] == 1
    assert result['failed_item_count'] == result['evaluation_failure_count'] == result['telemetry_failure_count'] == 0
    item, = result['item_results']
    output = item['output']
    question = questions[item['item_id']]
    assert request['item_ids'] == manifest['selected_item_ids'] == [item['item_id']]
    assert request['pipeline'] == output['pipeline_version'] == 'v2.17'
    assert request['cache_mode'] == manifest['answer_cache']['mode'] == 'bypass'
    assert output['question'] == question['question']
    assert item['trace_id'] == trace['trace_id']
    assert result['execution_id'] == manifest['execution_id'] == trace['execution_id']
    assert not [t for t in output['agent_trace'] if t.get('error')]
    obs = trace['observations']
    by = {o['id']: o for o in obs}
    for o in obs:
        assert o['startTime'] <= o['endTime'], (directory, o['name'])
        parent = by.get(o.get('parentObservationId'))
        if parent:
            assert parent['startTime'] <= o['startTime'] <= o['endTime'] <= parent['endTime'], (directory, o['name'])
    assert sum(o['name'] == 'graph node: final' for o in obs) == 1
    assert manifest['pipeline']['execution_identity']['source_fingerprint'] == manifest['pipeline']['source_fingerprint']
    baseline = question['baselines'][output['agent_provider']]
    rows.append({'label': directory.name, 'execution_id': result['execution_id'],
        'source_fingerprint': manifest['pipeline']['source_fingerprint'],
        'managed_evaluators_equal_to_baseline': manifest['evaluator']['managed_evaluators'] == fixed['sources'][baseline['source_experiment_id']]['evaluator']['managed_evaluators'],
        'score': item['correctness_score'], 'baseline_score': baseline['correctness']['value'],
        'latency_seconds': output['latency_seconds'], 'baseline_latency_seconds': baseline['latency_seconds'],
        'artifact_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in ('request.json', 'manifest.json', 'results.json', 'trace.json', 'review.json')}})
assert len({r['source_fingerprint'] for r in rows}) == 1
print(json.dumps({'scope': 'Retained attempts only; not full Step 8 completion or Step 9 acceptance',
                  'checks': 'single-item/cache/source/identity/tool-errors/trace-parent-timing/single-finalization',
                  'attempts': rows}, indent=2))
