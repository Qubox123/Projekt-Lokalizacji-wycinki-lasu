"""Podsumowanie logów z konsoli węzła (linie `t=... p=... alarm=...`), jeden plik = jeden scenariusz.

    python firmware/tools/analyze_logs.py logi/cisza.log logi/pila_1m.log logi/rozmowa.log

Dla każdego pliku: liczba okien, poziom dźwięku, rozkład p, odsetek okien powyżej progów
i odsetek okien z alarmem. Pliki z "pila" w nazwie traktowane są jako scenariusze z piłą
(wysoki odsetek = dobrze), pozostałe jako tło (wysoki odsetek = fałszywe alarmy).
"""

import re
import sys
from pathlib import Path

import numpy as np

FIELD = re.compile(r"(\w+)=([-\d.]+)")


def parse(path):
    rows = []
    for line in Path(path).read_text(errors="replace").splitlines():
        f = dict(FIELD.findall(line))
        if "p" in f and "alarm" in f:
            rows.append(f)
    return rows


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(f"{'scenariusz':22s} {'okien':>5s} {'hp_dBFS':>8s} {'p med':>6s} {'p p90':>6s} "
          f"{'p max':>6s} {'>0.6':>6s} {'>0.8':>6s} {'alarm':>6s}")
    for path in sys.argv[1:]:
        rows = parse(path)
        if not rows:
            print(f"{Path(path).stem:22s} brak linii z p=")
            continue
        p = np.array([float(r["p"]) for r in rows])
        alarm = np.array([int(float(r["alarm"])) for r in rows])
        level = np.median([float(r["hp_dbfs"]) for r in rows]) if "hp_dbfs" in rows[0] else np.nan
        kind = "PIŁA" if "pila" in Path(path).stem.lower() else "tło"
        print(f"{Path(path).stem:22s} {len(p):5d} {level:8.1f} {np.median(p):6.2f} "
              f"{np.percentile(p, 90):6.2f} {p.max():6.2f} {(p > 0.6).mean():6.0%} "
              f"{(p > 0.8).mean():6.0%} {alarm.mean():6.0%}  [{kind}]")
        if "ovf" in rows[0] and any(float(r["ovf"]) for r in rows):
            print("   uwaga: ovf > 0, płytka gubiła próbki")


if __name__ == "__main__":
    main()
