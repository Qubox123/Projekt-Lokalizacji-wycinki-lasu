"""Badanie synchronizacji: utrata SYNC_REPLY i narastanie błędu zegara.

Model symulacyjny, NIE pomiary z modułów LoRa.
Używa Clock/exchange z istniejącego simulator/clock_sync.py.

Przykład:
 python3 simulator/loss_experiment.py --duration 300 --trials 30 \
   --intervals 10,30,60 --loss-rates 0,0.1,0.3 --csv results/sync_loss.csv
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

from clock_sync import Clock, exchange

SENSORS = (
    Clock(350_000, 12),
    Clock(-175_000, -18),
    Clock(730_000, 25),
)


def percentile(values: list[float], q: float) -> float | None:
    """Percentyl z liniową interpolacją; q w [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


@dataclass
class Result:
    attempts: int
    received: int
    abs_errors_us: list[float]
    ages_s: list[float]
    evaluated: int
    unsynchronized_seconds: int


def simulate(clock: Clock, duration_s: int, interval_s: int,
             loss_rate: float, rng: random.Random,
             jitter_us: float = 3000, asymmetry_us: float = 2000) -> Result:
    """Co sekundę oceniaj skorygowany czas, używając OSTATNIEGO offsetu.

    SYNC_REPLY jest modelowane jako utracone z prawdopodobieństwem loss_rate.
    Nie ma retransmisji, drift compensation ani filtrowania.
    """
    if duration_s <= 0 or interval_s <= 0 or not (0 <= loss_rate <= 1):
        raise ValueError("duration i interval > 0, loss_rate w przedziale [0, 1]")
    if jitter_us < 0:
        raise ValueError("jitter_us musi być >= 0")

    correction = None
    last_reply_ref_us = None
    attempts = received = unsynchronized_seconds = 0
    abs_errors = []
    ages = []
    for sec in range(duration_s + 1):
        ref_now_us = sec * 1_000_000.0
        if sec % interval_s == 0:
            attempts += 1
            if rng.random() >= loss_rate:
                measurement = exchange(
                    clock, ref_now_us, rng,
                    jitter_us=jitter_us, asymmetry_us=asymmetry_us
                )
                received += 1
                correction = measurement.offset_estimate_us
                # Zamiana czasu lokalnego t4 na rzeczywisty czas centrali.
                last_reply_ref_us = (
                    (measurement.local_at_reply_us - clock.offset_us)
                    / (1 + clock.drift_ppm / 1_000_000)
                )
                # Mierzymy stan po zakończeniu wymiany (odpowiedź trwa > 0 ms).
                ref_now_us = last_reply_ref_us
        if correction is None:
            unsynchronized_seconds += 1
            continue
        # Skorygowana lokalna skala czasu minus prawdziwy czas centrali.
        error_us = clock.read(ref_now_us) + correction - ref_now_us
        abs_errors.append(abs(error_us))
        ages.append(max(0.0, (ref_now_us - last_reply_ref_us) / 1_000_000))
    return Result(
        attempts=attempts,
        received=received,
        abs_errors_us=abs_errors,
        ages_s=ages,
        evaluated=len(abs_errors),
        unsynchronized_seconds=unsynchronized_seconds,
    )


def run_matrix(duration_s: int, trials: int, intervals: list[int],
               loss_rates: list[float], jitter_us: float,
               asymmetry_us: float, seed: int = 42) -> list[dict]:
    if trials <= 0:
        raise ValueError("trials musi być > 0")
    rows = []
    for interval in intervals:
        for loss_rate in loss_rates:
            for node_id, clock in enumerate(SENSORS, 1):
                errors = []
                ages = []
                attempts = received = missing = 0
                for trial in range(trials):
                    rng = random.Random(seed + node_id * 1_000_003
                                        + interval * 1009
                                        + round(loss_rate * 1000) * 131
                                        + trial)
                    result = simulate(
                        clock, duration_s, interval, loss_rate, rng,
                        jitter_us, asymmetry_us
                    )
                    errors.extend(result.abs_errors_us)
                    ages.extend(result.ages_s)
                    attempts += result.attempts
                    received += result.received
                    missing += result.unsynchronized_seconds
                rows.append({
                    "node": node_id,
                    "interval_s": interval,
                    "loss_rate": loss_rate,
                    "attempts": attempts,
                    "replies": received,
                    "reception_pct": round(100 * received / attempts, 2),
                    "unsynchronized_seconds": missing,
                    "mean_abs_error_us": round(statistics.mean(errors), 2) if errors else "",
                    "p95_abs_error_us": round(percentile(errors, 95), 2) if errors else "",
                    "max_abs_error_us": round(max(errors), 2) if errors else "",
                    "max_correction_age_s": round(max(ages), 2) if ages else "",
                })
    return rows


def csv_output(rows: list[dict], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=300, help="sekundy na próbę")
    parser.add_argument("--trials", type=int, default=30, help="liczba prób")
    parser.add_argument("--intervals", default="10,30,60", help="sekundy, oddzielone przecinkiem")
    parser.add_argument("--loss-rates", default="0,0.1,0.3", help="ułamki, np. 0,0.1,0.3")
    parser.add_argument("--jitter-us", type=float, default=3000)
    parser.add_argument("--asymmetry-us", type=float, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--csv", type=Path, default=Path("results/sync_loss.csv"))
    args = parser.parse_args()
    try:
        intervals = [int(s.strip()) for s in args.intervals.split(",")]
        losses = [float(s.strip()) for s in args.loss_rates.split(",")]
        if not intervals or not losses or any(i <= 0 for i in intervals) or any(
            not (0 <= p <= 1) for p in losses
        ):
            raise ValueError("Nieprawidłowe przedziały lub prawdopodobieństwa")
        rows = run_matrix(
            args.duration, args.trials, intervals, losses,
            args.jitter_us, args.asymmetry_us, args.seed
        )
    except ValueError as exc:
        parser.error(str(exc))
    csv_output(rows, args.csv)
    print("SYMULACJA — brak pomiarów radiowych. Brak kompensacji dryftu.")
    print("node  okres[s] straty[%] odebrane[%]  p95|błąd|[us]  max|błąd|[us]")
    for row in rows:
        print(f"{row['node']:>4} {row['interval_s']:>9} "
              f"{100*row['loss_rate']:>9.0f} {row['reception_pct']:>10.1f} "
              f"{str(row['p95_abs_error_us']):>15} "
              f"{str(row['max_abs_error_us']):>15}")
    print(f"CSV: {args.csv}")


if __name__ == "__main__":
    main()
