"""Retain an explicit human/agent review and selected attempt; never run inference."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('label')
p.add_argument('--note', required=True)
p.add_argument('--select', action='store_true')
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
f = root / 'docs/experiments/langgraph-v2.17-step8'
review = json.loads(subprocess.check_output([sys.executable, str(root/'scripts/langgraph_review_live_item.py'), a.label], text=True))
assert review['status'] == 'completed' and not review['trace_checks'] and not review['telemetry_errors'], review
review['manual_review'] = a.note
(f/a.label/'review.json').write_text(json.dumps(review, indent=2)+'\n')
v = json.loads((f/'progress.json').read_text())
if a.select:
    key = a.label.rsplit('-a', 1)[0]
    v['selected_attempts'][key] = a.label
v['remaining_question_provider_pairs'] = 20-len(v['selected_attempts'])
v['attempts'] = []
for d in sorted(f.glob('*-q??-a?')):
    if not (d/'results.json').exists():
        continue
    r = json.loads((d/'results.json').read_text())
    m = json.loads((d/'manifest.json').read_text())
    i, = r['item_results']
    v['attempts'].append({'label':d.name,'correctness':i['correctness_score'],
        'latency_seconds':i['output'].get('latency_seconds'),'execution_id':r['execution_id'],
        'source_fingerprint':m['pipeline']['source_fingerprint']})
(f/'progress.json').write_text(json.dumps(v, indent=2)+'\n')
print(json.dumps(review, indent=2))
