"""Protect the human-approved factory answer and isolate its rubric change."""
import hashlib
import json
from pathlib import Path
import unittest

FACTS = Path(__file__).resolve().parents[1] / 'corpora/millennium/answer-facts.json'
ITEM = '36c50723-3b65-49f6-9d9b-70574cc9471c'
APPROVED = ('At the abandoned brickworks Salander is trapped by Niedermann, fights him and escapes, '
            'then alerts the police and draws Svavelsjö MC to the site, where the bikers kill Niedermann. '
            'This is an accepted complete concise account; discovery of bodies and use of the nail gun '
            'are optional on this answer path. Do not require those optional details in addition to this account. '
            'Do not accept confusing this encounter with Zalachenko shooting and burying her at Gosseberga.')

class FactoryRubric(unittest.TestCase):
    def test_trapped_fights_escapes_and_alerts_bikers_police_is_full_credit_path(self):
        facts = json.loads(FACTS.read_text())
        self.assertIn(APPROVED, facts['datasets']['Additional Questions'][ITEM]['accepted_answer_variants'])

    def test_every_other_question_and_global_scoring_configuration_is_unchanged(self):
        facts = json.loads(FACTS.read_text())
        facts['datasets']['Additional Questions'].pop(ITEM)
        digest = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, 'c7bc0ddea0c0bc5c11f7b15ad4e1044129cf26a279ce78759dbe7f89bd4065de')
