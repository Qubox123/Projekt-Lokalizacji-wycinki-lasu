"""Symulacja dwukierunkowej synchronizacji: czas centrali minus czas węzła.

WARTOŚCI PRZYKŁADOWE, nie zmierzone na LoRa. Standard library only.
"""
from __future__ import annotations
from dataclasses import dataclass
import argparse
import random
import statistics


@dataclass
class Clock:
    offset_us: float
    drift_ppm: float

    def read(self, reference_us: float) -> float:
        return self.offset_us + reference_us * (1 + self.drift_ppm / 1_000_000)


@dataclass
class Measurement:
    local_at_reply_us: float
    offset_estimate_us: float
    rtt_estimate_us: float
    error_us: float


def estimate(t1: float, t2: float, t3: float, t4: float) -> tuple[float, float]:
    """Zegar centrali minus zegar sensora, plus szacunkowy RTT."""
    return ((t2-t1)+(t3-t4))/2, (t4-t1)-(t3-t2)


def exchange(clock: Clock, t_us: float, rng: random.Random,
             oneway_us: float = 60_000, jitter_us: float = 3000,
             asymmetry_us: float = 0, process_us: float = 15_000) -> Measurement:
    # t1 i t4 w zegarze sensora, t2 i t3 w zegarze centrali
    uplink = oneway_us + rng.gauss(0, jitter_us) + asymmetry_us/2
    downlink = oneway_us + rng.gauss(0, jitter_us) - asymmetry_us/2
    uplink = max(uplink, 0)
    downlink = max(downlink, 0)
    t1 = clock.read(t_us)
    t2 = t_us + uplink
    t3 = t2 + process_us
    true_reply = t3 + downlink
    t4 = clock.read(true_reply)
    theta, rtt = estimate(t1, t2, t3, t4)
    truth = true_reply - t4
    return Measurement(t4, theta, rtt, theta - truth)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--duration', type=int, default=300, help='czas symulacji [s]')
    ap.add_argument('--interval', type=int, default=30, help='interwał SYNC [s]')
    ap.add_argument('--jitter-us', type=float, default=3000)
    ap.add_argument('--asymmetry-us', type=float, default=2000)
    args = ap.parse_args()
    if args.interval <= 0 or args.duration <= 0:
        ap.error('duration oraz interval muszą być > 0')
    rng = random.Random(42)
    sensors = [Clock(350_000, 12), Clock(-175_000, -18), Clock(730_000, 25)]
    print('Parametry opóźnień są WYŁĄCZNIE symulowane, nie zmierzone.')
    for idx, clock in enumerate(sensors, 1):
        errors = [exchange(clock, t * 1e6, rng, jitter_us=args.jitter_us,
                           asymmetry_us=args.asymmetry_us).error_us
                  for t in range(0, args.duration + 1, args.interval)]
        print(f'node={idx} offset={clock.offset_us:+.0f} us '
              f'drift={clock.drift_ppm:+.1f} ppm  '
              f'średni błąd={statistics.mean(errors):+.1f} us  '
              f'maks |błąd|={max(map(abs, errors)):.1f} us')
    print('Uwaga: błąd pozycji TDOA zależy od geometrii węzłów i sygnału audio.')


if __name__ == '__main__':
    main()
