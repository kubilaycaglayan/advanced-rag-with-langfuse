"""Prepare one QA1 observation; Langfuse executes all scoring."""
import json
import uuid
from pathlib import Path
import requests
from langfuse import Langfuse
from app.prompt_assets import _api
from app.quality_metrics import fetch_observations, extract_trace, faithfulness_context, load_qrels, DEFAULT_QRELS
from app.quality_evaluators.rules import OBSERVATION_NAME, observation_metadata, reconcile as reconcile_rules

TRACE_ID = 'a18f003e157b35c8c10e455e5a7b6551'
ITEM_ID = '785e319a-89a1-5950-96cf-f99a23162a87'


def main():
    client = Langfuse()
    observations = fetch_observations(client, TRACE_ID)
    if len(observations) >= 200:
        raise RuntimeError('Observation pagination needs handling before this test')
    calls, union, _, answer, _ = extract_trace(observations)
    context, error = faithfulness_context(observations)
    if error or not answer:
        raise RuntimeError(error or 'Missing answer')
    qrels, passages = load_qrels(DEFAULT_QRELS, 'QA.csv', ITEM_ID)
    item = qrels['datasets']['QA.csv'][ITEM_ID]
    payload = {
        'question': item['question'], 'answer': answer, 'agent_context': context,
        'direct_gold_ids': [p['short_id'] for p in passages if p['relevance'] == 'direct'],
        'search_calls': [vars(c) for c in calls], 'union_passage_ids': sorted(union),
        'question_type': item.get('question_type'), 'single_evidence': item.get('single_evidence', False),
    }
    base, auth = _api()
    response = requests.get(base + '/api/public/v2/evaluators', auth=auth, params={'limit': 100}, timeout=20)
    response.raise_for_status()
    names = {'millennium-qm-retrieval', 'millennium-qm-faithfulness', 'millennium-qm-relevancy'}
    evaluators = [r for r in response.json()['data'] if r['name'] in names]
    if len(evaluators) != 3 or any(r['status'] != 'active' for r in evaluators):
        raise RuntimeError('Expected exactly three active evaluators')
    rules = reconcile_rules(write=True)
    run_id = uuid.uuid4().hex
    manifest = {'trace_id': TRACE_ID, 'item_id': ITEM_ID, 'rules': rules, 'run_id': run_id,
                'evaluators': [{k:r[k] for k in ('id', 'name', 'version', 'versionId')} for r in evaluators]}
    path = Path(f'data/millennium/quality-reviews/native-qa1-{run_id}.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with client.start_as_current_observation(trace_context={'trace_id': TRACE_ID}, name=OBSERVATION_NAME,
                                                as_type='span', input=payload,
                                                metadata=observation_metadata(item,
                                                          quality_evaluator_test=True, item_id=ITEM_ID,
                                                          qrels_version=qrels.get('version'),
                                                          source_trace_id=TRACE_ID, measurement_run_id=run_id)) as observation:
            manifest['observation_id'] = observation.id
            observation.update(output={'status': 'inputs prepared; scoring runs in Langfuse'})
        client.flush()
        path.write_text(json.dumps(manifest, indent=2))
        print(json.dumps(manifest, indent=2))
    finally:
        client.shutdown()


if __name__ == '__main__':
    main()
