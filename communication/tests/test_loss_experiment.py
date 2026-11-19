import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulator"))
from clock_sync import Clock
from loss_experiment import percentile, simulate, run_matrix


class TestLossExperiment(unittest.TestCase):
    def test_no_noise_no_drift(self):
        result = simulate(
            Clock(100_000, 0), duration_s=120, interval_s=30,
            loss_rate=0, rng=random.Random(4),
            jitter_us=0, asymmetry_us=0,
        )
        self.assertEqual(result.received, 5)
        self.assertAlmostEqual(max(result.abs_errors_us), 0.0)

    def test_all_replies_lost(self):
        result = simulate(
            Clock(100_000, 20), duration_s=120, interval_s=30,
            loss_rate=1, rng=random.Random(4),
        )
        self.assertEqual(result.received, 0)
        self.assertEqual(result.evaluated, 0)
        self.assertEqual(result.unsynchronized_seconds, 121)

    def test_drift_holdover_without_replies(self):
        clock = Clock(100_000, 25)
        correction_at_zero = -clock.offset_us
        time_us = 60_000_000
        error = clock.read(time_us) + correction_at_zero - time_us
        self.assertAlmostEqual(error, 1500.0)

    def test_percentile(self):
        self.assertEqual(percentile([0, 10, 20, 30, 40], 95), 38.0)
        self.assertIsNone(percentile([], 95))

    def test_matrix_schema(self):
        rows = run_matrix(60, 2, [30], [0], jitter_us=0, asymmetry_us=0)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["reception_pct"], 100)
        self.assertIn("p95_abs_error_us", rows[0])


if __name__ == "__main__":
    unittest.main()
