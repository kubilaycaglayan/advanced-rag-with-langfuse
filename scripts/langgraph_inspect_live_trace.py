"""Export one completed Step 8 item's live observations; no model calls."""
import argparse
import json
from pathlib import Path
from app.experiments.telemetry import _client

parser = argparse.ArgumentParser()
parser.add_argument('execution_id')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path('data/millennium/executions') / args.execution_id
result = json.loads((root / 'results.json').read_text())
client = _client()
trace_id = result['item_results'][0]['trace_id']
observations = []
cursor = None
while True:
    page = client.api.observations.get_many(trace_id=trace_id, limit=100, cursor=cursor,
        fields="core,basic,time,metadata,model,usage,metrics",
        expand_metadata="context_measurements,usage")
    observations.extend(o.dict() for o in page.data)
    following = page.meta.cursor if page.meta else None
    if not following or following == cursor:
        break
    cursor = following
args.output.write_text(json.dumps({'execution_id': args.execution_id, 'trace_id': trace_id,
                                  'observations': observations}, default=str, indent=2) + '\n')
print(json.dumps({'trace_id': trace_id, 'observations': len(observations),
                  'names': [o['name'] for o in observations]}, indent=2))
