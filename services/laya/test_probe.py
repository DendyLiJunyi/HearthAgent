"""Benchmark accounting tests; no model, GPU, or third-party imports required."""
import unittest

from probe import demo_state, latency_summary


class LatencySummaryTests(unittest.TestCase):
    def test_demo_state_matches_rust_sorted_objects_recursively(self):
        def check(value):
            if isinstance(value, dict):
                self.assertEqual(list(value), sorted(value))
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        state = demo_state()
        self.assertEqual(state["session_id"], "synthetic-laya-demo")
        self.assertEqual(state["revision"], 1)
        check(state)

    def test_nearest_rank_and_median_use_all_samples(self):
        values = list(range(20, 0, -1))
        self.assertEqual(latency_summary(values), {"median_ms": 10.5, "p95_ms": 19})
        self.assertEqual(values[0], 20)

    def test_single_sample(self):
        self.assertEqual(latency_summary([2.5]), {"median_ms": 2.5, "p95_ms": 2.5})

    def test_invalid_measurements(self):
        for values in ([], [-1], [float("nan")], [float("inf")]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                latency_summary(values)


if __name__ == "__main__":
    unittest.main()
