"""Compare recorded organization runs without invoking providers or changing scores."""
import hashlib
import json
from pathlib import Path

ROOT = Path('data/millennium/comparisons/2026-11-25-organization')
SELECTION = Path('docs/experiments/2026-11-25-organization-comparison.json')
OUTPUT = Path('docs/experiments/2026-11-25-organization-results.json')


def artifact(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def item_summary(item):
    output = item.get('output') or {}
    return {
        'trace_id': item.get('trace_id'),
        'failed': item['failed'],
        'error': output.get('error'),
        'answer': output.get('answer'),
        'citations': output.get('citations'),
        'scores': {row['name']: row['value'] for row in item.get('evaluations', [])},
        'evaluations': item.get('evaluations', []),
        'latency_seconds': output.get('latency_seconds'),
        'tool_calls': output.get('tool_calls'),
        'agent_stopped': output.get('agent_stopped'),
        'agent_usage': output.get('agent_usage'),
    }


def main():
    selection = json.loads(SELECTION.read_text())
    report = {'complete_sample': True, 'contracts_identical': False,
              'comparisons': [], 'quality_declines': [], 'new_failures': [], 'missing_runs': []}
    for dataset, snapshot in selection['datasets'].items():
        for provider in ('ollama', 'openai'):
            paths = {phase: ROOT / f"{phase}-{dataset.replace(' ', '-')}-{provider}.json"
                     for phase in ('baseline', 'final')}
            if not all(path.exists() for path in paths.values()):
                report['missing_runs'].append({'dataset': dataset, 'provider': provider})
                report['complete_sample'] = False
                continue
            runs = {phase: json.loads(path.read_text()) for phase, path in paths.items()}
            expected = {item['id'] for item in snapshot['items']}
            for phase, run in runs.items():
                assert run['dataset_id'] == snapshot['id'], (dataset, phase, 'dataset changed')
                assert run['dataset_version'] == snapshot['version'], (dataset, phase, 'version changed')
                assert {item['item_id'] for item in run['item_results']} == expected, (dataset, phase, 'items changed')
            assert runs['baseline']['dataset_snapshot_sha256'] == runs['final']['dataset_snapshot_sha256']
            assert runs['baseline']['managed_evaluators'] == runs['final']['managed_evaluators']
            by_phase = {phase: {item['item_id']: item for item in run['item_results']}
                        for phase, run in runs.items()}
            comparison = {'dataset': dataset, 'provider': provider,
                          'runs': {phase: {key: run.get(key) for key in (
                              'execution_id', 'status', 'dataset_run_url', 'evaluator_id', 'scores',
                              'failed_item_count', 'evaluation_failure_count', 'telemetry_failure_count',
                              'agent_usage', 'abstention_count')} for phase, run in runs.items()},
                          'artifacts': {phase: artifact(path) for phase, path in paths.items()}, 'items': []}
            for selected in snapshot['items']:
                item_id = selected['id']
                pair = {phase: item_summary(items[item_id]) for phase, items in by_phase.items()}
                comparison['items'].append({'item_id': item_id, 'question': selected['input'], **pair})
                if pair['final']['failed'] and not pair['baseline']['failed']:
                    report['new_failures'].append({'dataset': dataset, 'provider': provider, 'item_id': item_id})
                for name, final in pair['final']['scores'].items():
                    baseline = pair['baseline']['scores'].get(name)
                    if isinstance(final, (int, float)) and isinstance(baseline, (int, float)) and final < baseline:
                        report['quality_declines'].append({'dataset': dataset, 'provider': provider,
                            'item_id': item_id, 'metric': name, 'baseline': baseline, 'final': final})
            report['comparisons'].append(comparison)
    contract_paths = [ROOT / f'{phase}-contracts.json' for phase in ('baseline', 'final')]
    if all(path.exists() for path in contract_paths):
        report['contracts_identical'] = json.loads(contract_paths[0].read_text()) == json.loads(contract_paths[1].read_text())
        report['contract_artifacts'] = [artifact(path) for path in contract_paths]
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: report[key] for key in ('complete_sample', 'contracts_identical',
                                                 'quality_declines', 'new_failures', 'missing_runs')}, indent=2))


if __name__ == '__main__':
    main()
