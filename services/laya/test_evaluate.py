"""Evaluation integrity tests without loading the model."""
import copy
import unittest

from evaluate import ordered, score, trials


class EvaluationTests(unittest.TestCase):
    def test_permutations_preserve_semantics_and_expected_answer(self):
        suite = list(trials())
        self.assertEqual(len(suite), 30)
        for trial in suite:
            self.assertIn(trial["expected"], trial["mapping"].values())
            self.assertEqual(set(trial["mapping"]), set(trial["questions"]["action"]["criteria"]))
        for forward, reverse in zip(suite[::2], suite[1::2]):
            self.assertEqual(forward["state"], reverse["state"])
            self.assertNotEqual(list(forward["state"]), list(reverse["state"]))
            self.assertEqual(ordered(reverse["state"]), forward["state"])

    def test_score_maps_labels_before_scoring_and_separates_confidence(self):
        trial = list(trials())[2]  # Reversed candidate order, canonical state.
        response = self.response()
        result = score(response, trial)
        self.assertEqual(result["choice"], "attack")
        self.assertTrue(result["correct"])
        self.assertFalse(result["accepted_at_0_8"])
        self.assertFalse(result["first_candidate_correct"])

    @staticmethod
    def response():
        return {"answers": {"action": {"type": "choice", "choice": "c1",
            "probabilities": {"c0": 0.3, "c1": 0.7}, "answer_confidence": 0.7,
            "abstention": "passed"}}, "usage": {"truncated": False,
            "state_tokens_dropped": 0, "truncated_questions": []}}

    def test_invalid_and_truncated_results_fail(self):
        trial = next(trials())
        mutations = [
            ("usage", "truncated", True), ("usage", "state_tokens_dropped", 1),
            ("usage", "truncated_questions", ["action"]),
            ("answer", "choice", "unknown"), ("answer", "answer_confidence", float("nan")),
            ("answer", "probabilities", {"c0": 0.5, "c1": 0.6}),
            ("answer", "probabilities", {"c0": 0.9, "c1": 0.1}),
        ]
        for section, key, value in mutations:
            response = copy.deepcopy(self.response())
            node = response["usage"] if section == "usage" else response["answers"]["action"]
            node[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                score(response, trial)


if __name__ == "__main__":
    unittest.main()
