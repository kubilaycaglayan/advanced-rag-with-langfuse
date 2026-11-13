"""Check the routing contract against the filters sent to Langfuse."""
import unittest

from app.quality_evaluators.rules import definitions, observation_metadata, OBSERVATION_NAME


class QualityRoutingTests(unittest.TestCase):
    def test_question_types_route_to_expected_evaluators(self):
        ids = {f"millennium-qm-{name}": name for name in ("retrieval", "faithfulness", "relevancy")}
        rules = definitions(ids)
        for item, expected in [
            ({}, {"retrieval", "faithfulness", "relevancy"}),
            ({"single_evidence": True, "question_type": "single_evidence"},
             {"retrieval", "faithfulness", "relevancy"}),
            ({"question_type": "broad"}, {"faithfulness", "relevancy"}),
        ]:
            with self.subTest(item=item):
                metadata = observation_metadata(item)
                selected = set()
                for rule in rules:
                    matches = []
                    for condition in rule['filter']:
                        value = (OBSERVATION_NAME if condition['column'] == 'name'
                                 else metadata.get(condition['key']))
                        operator = condition['operator']
                        matches.append(value in condition['value'] if operator == 'any of'
                                       else value is not None if operator == 'is set'
                                       else value == condition['value'])
                    if all(matches):
                        selected.update(e['evaluatorId'] for e in rule['evaluatorAssignments'])
                self.assertEqual(selected, expected)

    def test_invalid_labels_cannot_enable_retrieval(self):
        for item in ({"question_type": "unknown"},
                     {"question_type": "broad", "single_evidence": True}):
            with self.assertRaises(ValueError):
                observation_metadata(item)


if __name__ == '__main__':
    unittest.main()
