"""Export Step 1 recorded inputs only; never invokes a model or writes the experiment DB.

Run from the repository root with Python 3.12 (standard library only).
"""
import hashlib
import json
from pathlib import Path
import sqlite3

DEST = Path('docs/experiments/langgraph-v2.17-step1')
REFERENCES = {
    'QA.csv': {'openai': '4dc5a0a71e072c74', 'ollama': '4ff5ebd1a66dbfb8'},
    'set3': {'openai': '37ebe85de2796617', 'ollama': '163cfd81374ea8b8'},
    'right-set-3': {'openai': 'c2cde1e05faa6f40', 'ollama': '99b35b171b966af9'},
    'Additional Questions': {'openai': '4411d1a1728f4990', 'ollama': 'b2e7fb1676745447'},
}
# Coverage and shared historical availability determine selection, not baseline scores.
SELECTION = [
    ('QA.csv', '02ad392b-b200-58ce-a96d-f7cd57a5a252', ['direct_fact'], 'First smoke: bounded factual question with recorded results for both providers.'),
    ('QA.csv', 'a6ee3143-428c-5d8e-8d8e-d131dc92ac54', ['false_premise'], 'False death premise and premise evidence probe.'),
    ('QA.csv', '58343746-a482-480d-b6d4-3e86f468a95c', ['name'], 'Nickname identification.'),
    ('set3', 'ce841aab-a26b-512b-8fa9-ba28cf3b0f20', ['broad_narrative'], 'Broad multi-character evidence gathering.'),
    ('set3', 'cf527045-31e2-56b5-a91d-1fb1f13fdd71', ['direct_fact', 'true_account'], 'Official versus actual death account.'),
    ('right-set-3', '87382e52-ad6e-5336-9aa1-1b0d29cfc8ed', ['broad_narrative'], 'Whole-book narrative coverage.'),
    ('right-set-3', '10722a9f-1262-53ae-8f73-11ff27be91d2', ['sequence'], 'Court outcome and misspelled character name.'),
    ('right-set-3', 'a385d39a-767a-514a-a858-573e337356ad', ['name'], 'Misspelled Mikael and discovery of hacking.'),
    ('Additional Questions', '36c50723-3b65-49f6-9d9b-70574cc9471c', ['sequence'], 'Factory event sequence and later confrontation.'),
    ('Additional Questions', '45d561b9-ca5e-4c5d-83cb-04b610da13dc', ['speech', 'direct_fact'], 'Exact speech and moment precheck.'),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    with sqlite3.connect('file:data/millennium/experiments.sqlite3?mode=ro', uri=True) as db:
        records = {}
        wanted = {v for providers in REFERENCES.values() for v in providers.values()}
        for execution_id, payload, result in db.execute('SELECT execution_id,payload_json,result_json FROM executions WHERE result_json IS NOT NULL'):
            parsed = json.loads(result)
            if parsed.get('experiment_id') in wanted:
                assert parsed['experiment_id'] not in records
                records[parsed['experiment_id']] = (execution_id, json.loads(payload), parsed)
    sources = {}
    for dataset, providers in REFERENCES.items():
        for provider, experiment in providers.items():
            execution, request, result = records[experiment]
            path = Path(f'data/millennium/executions/{execution}/manifest.json')
            manifest = json.loads(path.read_text())
            snapshot = manifest['dataset_snapshot']
            assert snapshot['dataset_name'] == dataset
            sources[experiment] = {
                'dataset': dataset, 'provider': provider, 'execution_id': execution,
                'agent_model_identity': {
                    'name': manifest['pipeline'].get('agent_settings', {}).get('model', 'qwen3:8b'),
                    'provenance': 'recorded pipeline.agent_settings' if manifest['pipeline'].get('agent_settings') else 'assessment and best-performing-versions.md local QA fallback; legacy manifest omits agent settings',
                    'immutable_revision': 'Not recorded for historical answering-agent weights; current local digests are in starting-state.json',
                },
                'experiment_id': experiment, 'dataset_run_id': result['dataset_run_id'],
                'dataset_run_url': result['dataset_run_url'], 'request': request,
                'dataset_snapshot': {k: v for k, v in snapshot.items() if k != 'items'},
                'pipeline': {k: v for k, v in manifest['pipeline'].items() if k != 'source_manifest'},
                'index': manifest['index'], 'evaluator': manifest['evaluator'],
                'result_evaluator_id': result['evaluator_id'],
                'correctness_rescore': result.get('correctness_rescore'),
                'manifest_path': str(path), 'manifest_sha256': digest(path),
                'result_json_sha256': hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
                'selection_rule': 'Best recorded v2.16 listed in assessment' if provider == 'openai' else 'No listed local v2.16; latest listed local pipeline and best correctness within that version',
            }
    questions = []
    for dataset, item_id, tags, rationale in SELECTION:
        baselines = {}
        inputs = []
        for provider, experiment in REFERENCES[dataset].items():
            execution, _, result = records[experiment]
            manifest = json.loads(Path(sources[experiment]['manifest_path']).read_text())
            frozen = next(i for i in manifest['dataset_snapshot']['items'] if i['id'] == item_id)
            item = next(i for i in result['item_results'] if i['item_id'] == item_id)
            score = next(e for e in item['evaluations'] if e['name'] == 'answer_correctness_v2')
            original_score = score
            rescore_provenance = None
            if result.get('correctness_rescore', {}).get('accepted_as_actual'):
                rescore_path = Path(result['correctness_rescore']['artifact'])
                rescore = json.loads(rescore_path.read_text())
                rescored = next(i for i in rescore['items'] if i['item_id'] == item_id)
                score = rescored['evaluation']
                assert score['value'] == item['correctness_score']
                rescore_provenance = {'path': str(rescore_path), 'sha256': digest(rescore_path),
                                      'facts_version': rescore['facts_version'],
                                      'source_run': rescore['source_run']}
            output = item['output']
            assert not item['failed'] and isinstance(score['value'], (int, float))
            assert isinstance(output['latency_seconds'], (int, float)) and output['latency_seconds'] > 0
            inputs.append(frozen['input'])
            baselines[provider] = {
                'source_experiment_id': experiment, 'execution_id': execution,
                'trace_id': item['trace_id'], 'session_id': item['session_id'],
                'snapshot_item': frozen, 'correctness': score,
                'original_correctness': original_score, 'accepted_rescore': rescore_provenance,
                'current_scoring_facts': json.loads(Path('corpora/millennium/answer-facts.json').read_text())['datasets'].get(dataset, {}).get(item_id),
                'latency_seconds': output['latency_seconds'],
                'latency_definition': 'Recorded output.latency_seconds: query-and-answer duration, excluding evaluator latency.',
                'answer': output['answer'], 'answer_cache_status': item.get('answer_cache_status'),
                'pipeline_id': output.get('pipeline_id'), 'agent_stopped': output.get('agent_stopped'),
            }
        assert inputs[0] == inputs[1], (dataset, item_id)
        questions.append({'dataset': dataset, 'item_id': item_id, 'question': inputs[0]['question'],
                          'coverage': tags, 'selection_rationale': rationale, 'baselines': baselines})
    assert len(questions) == len({q['item_id'] for q in questions}) == 10
    result = {
        'schema_version': 1, 'target_pipeline': 'v2.17', 'step': 1,
        'starting_state': 'starting-state.json', 'starting_state_sha256': digest(DEST / 'starting-state.json'),
        'baseline_policy_source': '../../langgraph-refactor-assessment.md',
        'sample_policy': 'Exactly the same 10 question IDs for both providers; fixed order; equal item weights.',
        'first_smoke': {'dataset': questions[0]['dataset'], 'item_id': questions[0]['item_id'], 'provider': 'openai', 'cache_mode': 'bypass'},
        'missing_selected_historical_results': [],
        'sources': sources, 'questions': questions,
        'baseline_sample_means': {p: {
            'correctness': sum(q['baselines'][p]['correctness']['value'] for q in questions) / 10,
            'latency_seconds': sum(q['baselines'][p]['latency_seconds'] for q in questions) / 10,
        } for p in ('openai', 'ollama')},
    }
    (DEST / 'comparison-manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['baseline_sample_means'], indent=2))


if __name__ == '__main__':
    freeze()
