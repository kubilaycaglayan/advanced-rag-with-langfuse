"""Corpus isolation and provisional-label safeguards for quality evaluation."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.quality_evaluators import definitions
from app.quality_evaluators.client import project_api
from app.quality_evaluators.config import configuration
from app.quality_evaluators.rules import definitions as rule_definitions, observation_metadata
from app.quality_evaluators.submit import validate_source


class QualityCorpusTests(unittest.TestCase):
    def corpus(self, name):
        return patch.dict(os.environ, {'CORPUS_ID': name, 'CORPUS_ROOT': ''})

    def test_alienist_has_its_own_names_qrels_and_model_filters(self):
        with self.corpus('thealienist'):
            config = configuration()
            self.assertEqual(config.dataset, 'set-1')
            self.assertEqual(config.qrels.parent.name, 'thealienist')
            evaluators = definitions()
            self.assertTrue(all(e['name'].startswith('thealienist-qm-') for e in evaluators))
            self.assertNotIn('Blomkvist', str(evaluators))
            ids = {e['name']: e['name'] for e in evaluators}
            for rule in rule_definitions(ids):
                filters = {f.get('key'): f['value'] for f in rule['filter']}
                self.assertEqual(filters['pipeline_version'], 'v2.16')
                self.assertEqual(filters['agent_model'], 'gpt-6-luna')
                self.assertEqual(filters['agent_reasoning_effort'], 'high')

    def test_millennium_retains_existing_configuration(self):
        with self.corpus('millennium'):
            config = configuration()
            self.assertEqual(config.pipeline, 'v2.12')
            self.assertEqual(config.project, 'millenium')
            self.assertEqual(config.observation_name, 'millennium quality measurement')
            self.assertIn('Mikael', str(definitions()))

    def test_provisional_qrels_skip_retrieval_but_allow_answer_judges(self):
        with self.corpus('thealienist'):
            metadata = observation_metadata({'retrieval_metrics_ready': False})
            self.assertEqual(metadata['retrieval_evaluation'], 'skip')
            self.assertEqual(metadata['question_type'], 'normal')
            self.assertEqual(metadata['pipeline_version'], 'v2.16')

    def test_source_trace_must_match_configuration(self):
        with self.corpus('thealienist'):
            config = configuration()
            correct = {'pipeline_version': config.pipeline, **config.agent_settings}
            validate_source([SimpleNamespace(metadata=correct)], config)
            for change in ({'pipeline_version': 'v2.12'}, {'agent_reasoning_effort': 'low'},
                           {'corpus_id': 'millennium'}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_source([SimpleNamespace(metadata={**correct, **change})], config)
            with self.assertRaises(ValueError):
                validate_source([], config)

    @patch('app.quality_evaluators.client.requests.get')
    @patch('app.quality_evaluators.client._api', return_value=('http://langfuse', None))
    def test_wrong_project_is_rejected_before_writing(self, api, get):
        get.return_value.json.return_value = {'data': [{'name': 'millenium'}]}
        with self.corpus('thealienist'), self.assertRaises(ValueError):
            project_api()
