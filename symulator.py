"""Symulacja bramy: rejestruje 3 węzły, losuje miejsce wycinki, wysyła pakiety na serwer
i pokazuje, jak daleko od prawdziwego miejsca wyszedł wynik.

Uruchomienie (serwer musi działać: uvicorn app.main:app):
    python symulator.py
    python symulator.py 5 #pięć zdarzeń
"""
import sys
import time

import numpy as np
import requests

from app.localization import LocalFrame
from app.simulation import synth_packets

SERVER = "http://127.0.0.1:8000"
NODES = {"N1": (50.0535, 19.8560), "N2": (50.0560, 19.8590), "N3": (50.0535, 19.8620)}


def main(count: int) -> None:
    rng = np.random.default_rng()
    for node_id, (lat, lon) in NODES.items():
        requests.put(f"{SERVER}/nodes/{node_id}", json={"lat": lat, "lon": lon}).raise_for_status()

    frame = LocalFrame(np.mean([v[0] for v in NODES.values()]), np.mean([v[1] for v in NODES.values()]))
    xy = np.array([frame.to_xy(*v) for v in NODES.values()])

    for k in range(count):
        true_xy = rng.dirichlet([1, 1, 1]) @ xy
        t_emit_us = int(time.time() * 1e6)
        for p in synth_packets(NODES, frame.to_latlon(*true_xy), t_emit_us, rng):
            r = requests.post(f"{SERVER}/packets", json=p)
            r.raise_for_status()
        event = requests.get(f"{SERVER}/events/{r.json()['event_id']}").json()

        if event["status"] == "localized":
            x, y = frame.to_xy(event["lat"], event["lon"])
            err = np.hypot(x - true_xy[0], y - true_xy[1])
            print(f"Zdarzenie {event['id']}, ({event['lat']:.6f}, {event['lon']:.6f}), "
                  f"promień {event['accuracy_m']} m, błąd naprawdę: {err:.1f} m")
        else:
            print(f"Cięcie {k + 1}: zdarzenie {event['id']} ma status {event['status']}")
        if k < count - 1:
            time.sleep(3)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)