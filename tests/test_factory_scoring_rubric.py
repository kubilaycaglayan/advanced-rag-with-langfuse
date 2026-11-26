"""Protect the human-approved factory answer and isolate its rubric change."""
import hashlib
import json
from pathlib import Path
import unittest

FACTS = Path(__file__).resolve().parents[1] / 'corpora/millennium/answer-facts.json'
ITEM = '36c50723-3b65-49f6-9d9b-70574cc9471c'
class FactoryRubric(unittest.TestCase):
    def test_original_factory_alternative_remains_available(self):
        facts = json.loads(FACTS.read_text())
        variants = facts['datasets']['Additional Questions'][ITEM]['accepted_answer_variants']
        self.assertEqual(len(variants), 1)
        self.assertIn('Salander discovers bodies', variants[0])

    def test_primary_factory_path_requires_the_approved_core_events(self):
        item = json.loads(FACTS.read_text())['datasets']['Additional Questions'][ITEM]
        self.assertEqual(item['required_facts'], [
            'Salander was trapped in the abandoned brickworks with Niedermann',
            'She fought Niedermann and escaped',
            'She alerted the police and brought the biker gang to the site'])
        self.assertEqual(item['supporting_details'], [])

    def test_every_other_question_and_global_scoring_configuration_is_unchanged(self):
        facts = json.loads(FACTS.read_text())
        facts['datasets']['Additional Questions'].pop(ITEM)
        digest = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, 'c7bc0ddea0c0bc5c11f7b15ad4e1044129cf26a279ce78759dbe7f89bd4065de')
