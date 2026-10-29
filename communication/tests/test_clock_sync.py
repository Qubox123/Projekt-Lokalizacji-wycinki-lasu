import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'simulator'))
from clock_sync import Clock, estimate, exchange
import random

class TestSync(unittest.TestCase):
    def test_equal_delays_no_drift(self):
        # sensor o 1000 us do przodu. Czas centrali - lokalny = -1000 us.
        t1, t2, t3, t4 = 11000, 11000, 13000, 15000
        off, rtt = estimate(t1, t2, t3, t4)
        self.assertEqual(off, -1000)
        self.assertEqual(rtt, 2000)

    def test_perfect_simulated_link(self):
        clock = Clock(120000, 0)
        m = exchange(clock, 3_000_000, random.Random(5),
                     oneway_us=50000, jitter_us=0, asymmetry_us=0)
        self.assertAlmostEqual(m.error_us, 0)

    def test_asymmetry_creates_bias(self):
        clock = Clock(0, 0)
        m = exchange(clock, 1_000_000, random.Random(5),
                     oneway_us=50000, jitter_us=0, asymmetry_us=8000)
        self.assertAlmostEqual(m.error_us, 4000)

    def test_clock_drift(self):
        self.assertAlmostEqual(Clock(0, 20).read(300_000_000)-300_000_000, 6000)

if __name__ == '__main__':
    unittest.main()
