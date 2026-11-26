"""Run exactly one fixed Step 8 item, then retain its artifacts and live trace.

Advancement and correctness review remain manual; this never starts another item.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser()
p.add_argument('provider', choices=['openai', 'ollama'])
p.add_argument('question', type=int, choices=range(1, 11))
p.add_argument('attempt', type=int, choices=range(1, 4))
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
folder = root / 'docs/experiments/langgraph-v2.17-step8'
manifest = json.loads((root / 'docs/experiments/langgraph-v2.17-step1/comparison-manifest.json').read_text())
q = manifest['questions'][a.question - 1]
label = f'{a.provider}-q{a.question:02}-a{a.attempt}'
log = folder / f'{label}.log'
if log.exists():
    raise SystemExit('Attempt already exists; inspect its process/artifacts rather than restarting')
base = ['docker', 'compose', '-f', 'compose.yaml', '-f', '/tmp/millenium-langgraph-step2-compose.yaml',
        'run', '--no-deps', '--rm', '-T', '-v', f'{root}:/workspace', '-v',
        f'{shutil.which("git")}:/usr/local/bin/git:ro', '-w', '/workspace',
        '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory',
        '-e', 'GIT_CONFIG_VALUE_0=/workspace', '-e', 'PYTHONPATH=/workspace', 'app']
with log.open('w') as out:
    done = subprocess.run(base + ['python', '-m', 'app.experiments', '--dataset', q['dataset'],
        '--pipeline', 'v2.17', '--item-id', q['item_id'], '--cache-mode', 'bypass',
        '--settings', f'docs/experiments/langgraph-v2.17-step8/{a.provider}-settings.json',
        '--variant', f'langgraph-step8-{label}'], cwd=root, stdout=out, stderr=subprocess.STDOUT)
text = log.read_text()
start = text.find('{\n')
if start < 0:
    raise SystemExit(f'No CLI result; inspect {log}')
result, _ = json.JSONDecoder().raw_decode(text[start:])
eid = result['execution_id']
source = root / 'data/millennium/executions' / eid
dest = folder / label
dest.mkdir()
for name in ('request.json', 'manifest.json', 'results.json'):
    if (source / name).exists():
        shutil.copy2(source / name, dest / name)
print(json.dumps({'label': label, 'execution_id': eid, 'status': result['status'],
                  'items': [{'score': i['correctness_score'], 'latency': i['output'].get('latency_seconds'),
                             'answer': i['output'].get('answer')} for i in result.get('item_results', [])]}, indent=2))
if result.get('item_results'):
    subprocess.run(base + ['python', 'scripts/langgraph_inspect_live_trace.py', eid,
        '--output', f'docs/experiments/langgraph-v2.17-step8/{label}/trace.json'], cwd=root, check=True)
raise SystemExit(done.returncode)
