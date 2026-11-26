"""Inspect retained Step 8 evidence; never starts inference or chooses an attempt."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('label')
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
f = root / 'docs/experiments/langgraph-v2.17-step8' / a.label
r = json.loads((f / 'results.json').read_text())
m = json.loads((f / 'manifest.json').read_text())
t = json.loads((f / 'trace.json').read_text())
obs = t['observations']
by = {o['id']: o for o in obs}
item = r['item_results'][0]
out = item['output']
q = next(q for q in json.loads((root / 'docs/experiments/langgraph-v2.17-step1/comparison-manifest.json').read_text())['questions'] if q['item_id'] == item['item_id'])
provider = out['agent_provider']
errors = []
for o in obs:
    if o['name'].startswith('graph node:') and by.get(o['parentObservationId'], {}).get('name') != 'agent graph':
        errors.append('node parent: ' + o['name'])
    if o['endTime'] is None:
        errors.append('missing end: ' + o['name'])
    if o['name'].startswith('query agent model:'):
        parent = by.get(o['parentObservationId'])
        chain = []
        while parent:
            chain.append(parent['name'])
            parent = by.get(parent['parentObservationId'])
        if not any(n.startswith('graph node:') for n in chain):
            errors.append('generation outside graph node: ' + o['name'])
        if not o.get('usageDetails') or not o.get('metadata', {}).get('provider_prompt_tokens_available'):
            errors.append('missing model usage: ' + o['name'])
if sum(o['name'] == 'graph node: final' for o in obs) != 1:
    errors.append('finalization count')
print(json.dumps({'label': a.label, 'status': r['status'], 'score': item['correctness_score'],
    'baseline_score': q['baselines'][provider]['correctness']['value'],
    'latency': out['latency_seconds'], 'baseline_latency': q['baselines'][provider]['latency_seconds'],
    'answer': out['answer'], 'evaluations': item['evaluations'], 'stop': out['agent_stopped'],
    'tool_errors': [v for v in out['agent_trace'] if v.get('error')],
    'telemetry_errors': r['telemetry_errors'], 'trace_checks': errors,
    'trace_warnings': [(o['name'], o.get('statusMessage')) for o in obs if o['level'] in ('ERROR','WARNING')],
    'nodes': [o['name'] for o in sorted(obs, key=lambda o: (o['startTime'],o['id'])) if o['name'].startswith('graph node:')],
    'prompt_usage': [o.get('metadata',{}).get('provider_prompt_tokens') for o in obs if o['name'].startswith('query agent model:')],
    'source': m['pipeline'].get('source')}, indent=2))
