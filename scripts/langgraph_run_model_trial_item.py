"""Run one fixed comparison item with an explicitly selected Ollama agent model."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


p = argparse.ArgumentParser()
p.add_argument('question', type=int, choices=range(1, 11))
p.add_argument('attempt', type=int, choices=range(1, 4))
p.add_argument('--model', required=True)
p.add_argument('--slug', required=True, help='comparison folder slug, for example qwen3-8b')
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
folder = root / f'docs/experiments/langgraph-v2.17-{a.slug}'
manifest = json.loads((root / 'docs/experiments/langgraph-v2.17-step1/comparison-manifest.json').read_text())
q = manifest['questions'][a.question - 1]
label = f'q{a.question:02}-a{a.attempt}'
log = folder / f'{label}.log'
dest = folder / label
if log.exists() or dest.exists():
    raise SystemExit(f'{label} already exists; inspect its process/artifacts instead of restarting')
settings = folder / 'settings.json'
if not settings.exists():
    raise SystemExit(f'missing explicit settings file: {settings}')

base = ['docker', 'compose', '-f', 'compose.yaml', '-f', '/tmp/millenium-langgraph-step2-compose.yaml',
        'run', '--no-deps', '--rm', '-T', '-v', f'{root}:/workspace', '-v',
        f'{shutil.which("git")}:/usr/local/bin/git:ro', '-w', '/workspace',
        '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory',
        '-e', 'GIT_CONFIG_VALUE_0=/workspace', '-e', 'PYTHONPATH=/workspace', 'app']
variant = f'langgraph-v2.17-{a.slug}-{label}'
with log.open('w') as out:
    done = subprocess.run(base + ['python', '-m', 'app.experiments', '--dataset', q['dataset'],
        '--pipeline', 'v2.17', '--item-id', q['item_id'], '--cache-mode', 'bypass',
        '--settings', str(settings.relative_to(root)),
        '--variant', variant], cwd=root, stdout=out, stderr=subprocess.STDOUT)
text = log.read_text()
start = text.find('{\n')
if start < 0:
    raise SystemExit(f'No CLI result; inspect {log}')
result, _ = json.JSONDecoder().raw_decode(text[start:])
execution_id = result['execution_id']
source = root / 'data/millennium/executions' / execution_id
dest.mkdir(parents=True)
for name in ('request.json', 'manifest.json', 'results.json'):
    if (source / name).exists():
        shutil.copy2(source / name, dest / name)
print(json.dumps({'label': label, 'model': a.model, 'execution_id': execution_id,
                  'status': result['status'], 'items': [
                      {'score': i['correctness_score'], 'latency': i['output'].get('latency_seconds'),
                       'answer': i['output'].get('answer')}
                      for i in result.get('item_results', [])]}, indent=2))
if result.get('item_results'):
    subprocess.run(base + ['python', 'scripts/langgraph_inspect_live_trace.py', execution_id,
        '--output', f'{folder.relative_to(root)}/{label}/trace.json'], cwd=root, check=True)
raise SystemExit(done.returncode)
