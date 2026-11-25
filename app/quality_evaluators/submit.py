"""Prepare a corpus-scoped measurement; Langfuse executes the evaluators."""
import argparse
import json
import uuid

from langfuse import Langfuse

from app.corpus_config import corpus_data_dir
from app.evaluation.metrics import extract_trace, faithfulness_context, fetch_observations, load_qrels
from app.quality_evaluators.client import project_api
from app.quality_evaluators.config import configuration
from app.quality_evaluators.rules import observation_metadata, reconcile


def validate_source(observations, config):
    """Never relabel a trace from another corpus or model configuration."""
    metadata = [o.metadata for o in observations if isinstance(getattr(o, 'metadata', None), dict)]
    expected = {'pipeline_version': config.pipeline, **config.agent_settings}
    for key, value in expected.items():
        keys = (key, 'pipeline') if key == 'pipeline_version' else (key,)
        values = {m[k] for m in metadata for k in keys if isinstance(m.get(k), str)}
        if values != {value}:
            raise ValueError(f'Source trace must confirm {key}={value!r}; found {sorted(values)}')
    corpora = {m['corpus_id'] for m in metadata if isinstance(m.get('corpus_id'), str)}
    if corpora and corpora != {config.corpus}:
        raise ValueError('Source trace belongs to another corpus')


def submit(trace_id, dataset, item_id):
    config = configuration()
    project_api()
    qrels, passages = load_qrels(config.qrels, dataset, item_id)
    if qrels.get('corpus') != config.corpus:
        raise ValueError('Qrels belong to another corpus')
    item = qrels['datasets'][dataset][item_id]
    metadata = observation_metadata(item, item_id=item_id, dataset=dataset,
                                    qrels_version=qrels.get('version'), source_trace_id=trace_id)
    client = Langfuse()
    try:
        observations = fetch_observations(client, trace_id)
        if len(observations) >= 200:
            raise ValueError('Source trace requires observation pagination; submission refused')
        validate_source(observations, config)
        calls, union, _, answer, _ = extract_trace(observations)
        context, error = faithfulness_context(observations)
        if error or not answer:
            raise ValueError(error or 'Source trace has no answer')
        rules = reconcile()
        if any(rule['changed'] for rule in rules):
            raise ValueError('Install the configured evaluator rules before submitting measurements')
        run_id = uuid.uuid4().hex
        metadata['measurement_run_id'] = run_id
        payload = {'question': item['question'], 'answer': answer, 'agent_context': context,
                   'direct_gold_ids': [p['short_id'] for p in passages if p['relevance'] == 'direct'],
                   'search_calls': [vars(c) for c in calls], 'union_passage_ids': sorted(union),
                   'question_type': metadata['question_type'],
                   'single_evidence': item.get('single_evidence', False),
                   'retrieval_metrics_ready': metadata['retrieval_evaluation'] == 'enabled'}
        manifest = {'corpus': config.corpus, 'dataset': dataset, 'trace_id': trace_id,
                    'item_id': item_id, 'run_id': run_id, 'rules': rules}
        with client.start_as_current_observation(trace_context={'trace_id': trace_id},
                                                name=config.observation_name, as_type='span',
                                                input=payload, metadata=metadata) as observation:
            manifest['observation_id'] = observation.id
            observation.update(output={'status': 'inputs prepared; scoring runs in Langfuse'})
        client.flush()
        path = corpus_data_dir() / 'quality-reviews' / f'native-{item_id}-{run_id}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        return manifest
    finally:
        client.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace-id', required=True)
    parser.add_argument('--item-id', required=True)
    parser.add_argument('--dataset', default=configuration().dataset)
    args = parser.parse_args()
    print(json.dumps(submit(args.trace_id, args.dataset, args.item_id), indent=2))


if __name__ == '__main__':
    main()
