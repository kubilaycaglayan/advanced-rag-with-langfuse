"""Targeted repeats on either the original or reorganized source tree."""
import argparse
import importlib
import json
import uuid
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['baseline-repeat', 'final-repeat'])
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--provider', choices=['ollama', 'openai'], required=True)
    parser.add_argument('--item-id', action='append', required=True)
    args = parser.parse_args()
    original = Path('app/experiments.py').exists()
    experiments = importlib.import_module('app.experiments' if original else 'app.experiments.execution')
    store = importlib.import_module('app.experiment_store' if original else 'app.experiments.store')
    storage = store if original else importlib.import_module('app.storage')
    indexes = importlib.import_module('app.indexer' if original else 'app.indexing.passages')
    selection = json.loads(Path('docs/experiments/2026-11-25-organization-comparison.json').read_text())
    dataset = selection['datasets'][args.dataset]
    assert set(args.item_id) <= {item['id'] for item in dataset['items']}
    output = Path('data/millennium/comparisons/2026-11-25-organization')
    target = output / f"{args.phase}-{args.dataset.replace(' ', '-')}-{args.provider}.json"
    if target.exists():
        raise RuntimeError(f'Refusing to overwrite a recorded repeat: {target}')

    def existing_index(config):
        collection = indexes.index_identity(config)[0]
        indexes.validate_index(collection, config)
        return {'collection': collection}

    payload = {'dataset_name': args.dataset, 'dataset_id': dataset['id'],
               'dataset_version': dataset['version'], 'pipeline': 'v2.16',
               'settings': {'agent_provider': args.provider}, 'cache_mode': 'bypass',
               'item_ids': args.item_id, 'variant_label': f'organization-{args.phase}-{args.provider}'}
    storage.initialize()
    execution_id = str(uuid.uuid4())
    store.enqueue(execution_id, payload, None)
    print(f'Starting {args.phase}: {execution_id}; original layout={original}', flush=True)
    with patch.object(experiments, 'build_index', existing_index):
        result = experiments.execute_execution(execution_id)
    target.write_text(json.dumps(result, indent=2, default=str) + '\n')
    print(f"Finished {args.phase}: {result['status']}", flush=True)


if __name__ == '__main__':
    main()
