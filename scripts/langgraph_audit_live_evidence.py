"""Audit retained Step 8 artifacts without generation or baseline changes."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root / 'docs/experiments/langgraph-v2.17-step8'
fixed = json.loads((root / 'docs/experiments/langgraph-v2.17-step1/comparison-manifest.json').read_text())
questions = {q['item_id']: q for q in fixed['questions']}
progress = json.loads((folder/'progress.json').read_text())
final_manifest = json.loads((folder/'openai-q10-a2/manifest.json').read_text())['pipeline']
final_files = {r['path']:r['sha256'] for r in final_manifest['source_manifest']['files']}
rows = []
archived = []
for directory in sorted(folder.glob('*-q??-a?')):
    result = json.loads((directory / 'results.json').read_text())
    manifest = json.loads((directory / 'manifest.json').read_text())
    request = json.loads((directory / 'request.json').read_text())
    trace = json.loads((directory / 'trace.json').read_text())
    if result['status'] != 'completed':
        assert directory.name in progress['superseded_attempts'], directory
        assert directory.name not in progress['selected_attempts'].values()
        archived.append({'label':directory.name,'status':result['status'],
                         'reason':progress['superseded_attempts'][directory.name]})
        continue
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
    tool_errors = [t for t in output['agent_trace'] if t.get('error')]
    review = json.loads((directory / 'review.json').read_text())
    if tool_errors:
        assert review.get('manual_review'), ('Tool errors require explicit review', directory)
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
    rows.append({'label': directory.name, 'selected': directory.name in progress['selected_attempts'].values(),
        'execution_id': result['execution_id'],
        'source_fingerprint': manifest['pipeline']['source_fingerprint'],
        'managed_evaluators_equal_to_baseline': manifest['evaluator']['managed_evaluators'] == fixed['sources'][baseline['source_experiment_id']]['evaluator']['managed_evaluators'],
        'reviewed_tool_errors': tool_errors, 'manual_review': review.get('manual_review'),
        'score': item['correctness_score'], 'baseline_score': baseline['correctness']['value'],
        'latency_seconds': output['latency_seconds'], 'baseline_latency_seconds': baseline['latency_seconds'],
        'artifact_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in ('request.json', 'manifest.json', 'results.json', 'trace.json', 'review.json')}})
    files = {r['path']:r['sha256'] for r in manifest['pipeline']['source_manifest']['files']}
    changed = [k for k in files.keys() | final_files.keys() if files.get(k) != final_files.get(k)]
    assert changed in ([], ['app/agent/tools/scenes.py']), (directory, changed)
    if changed and directory.name in progress['selected_attempts'].values():
        assert item['item_id'] != '45d561b9-ca5e-4c5d-83cb-04b610da13dc'
        assert not any(t.get('tool') == 'scene_moment' for t in output['agent_trace'])
    rows[-1]['final_code_compatibility'] = 'exact source' if not changed else 'only unused moment helper call changed'
    override = progress.get('effective_correctness_overrides', {}).get(directory.name)
    if override:
        rescored = json.loads((folder/override['artifact']).read_text())
        actual = next(r for r in rescored['attempts'] if r['label'] == directory.name)
        assert actual['evaluation']['value'] == override['value']
        assert actual['latency_seconds'] == output['latency_seconds']
    rows[-1]['effective_correctness'] = override['value'] if override else item['correctness_score']
print(json.dumps({'scope': 'All completed retained attempts; structural evidence audit only, no Step 9 aggregate acceptance',
                  'checks': 'single-item/cache/source/identity/reviewed-tool-errors/trace-parent-timing/single-finalization',
                  'final_source_fingerprint': final_manifest['source_fingerprint'],
                  'archived_failed_attempts':archived, 'attempts': rows}, indent=2))
