"""Symulacja: udaje węzły, które słyszą piłę w znanym miejscu.
Używana w skrypcie symulator.py, żeby sprawdzić algorytm bez sprzętu."""
import numpy as np

from .localization import LocalFrame


def synth_packets(nodes: dict[str, tuple[float, float]], source: tuple[float, float],
                  t_emit_us: int, rng: np.random.Generator, fs: float = 100.0,
                  n: int = 200, c: float = 343.0, noise: float = 4.0) -> list[dict]:
    """nodes: {node_id: (lat, lon)}, source: (lat, lon) piły, t_emit_us: chwila cięcia.
    Zwraca listę pakietów w formacie JSON, takim jak wysyła brama."""
    frame = LocalFrame(np.mean([v[0] for v in nodes.values()]), np.mean([v[1] for v in nodes.values()]))
    sx, sy = frame.to_xy(*source)

    # Kształt dźwięku piły (wspólny dla wszystkich węzłów): narastanie, wahania obrotów, wygaszenie.
    dur = rng.uniform(0.8, 1.3)
    f1, f2 = rng.uniform(2, 6), rng.uniform(6, 12)
    ph1, ph2 = rng.uniform(0, 2 * np.pi, 2)

    def shape(tau):
        on = np.clip(tau / 0.08, 0, 1) * (tau >= 0)
        mod = 1 + 0.35 * np.sin(2 * np.pi * f1 * tau + ph1) + 0.2 * np.sin(2 * np.pi * f2 * tau + ph2)
        off = np.where(tau > dur, np.exp(-(tau - dur) / 0.1), 1.0)
        return on * mod * off

    packets = []
    for node_id, (lat, lon) in nodes.items():
        x, y = frame.to_xy(lat, lon)
        d = np.hypot(sx - x, sy - y)
        arrival = d / c                                   # [s] po chwili cięcia
        start = arrival - 0.5 + rng.uniform(-0.1, 0.1)    # węzeł zaczyna okno trochę przed dźwiękiem
        t = start + np.arange(n) / fs
        level = 180 * 60 / (60 + d)                       # dalej = ciszej
        env = 5 + level * shape(t - arrival) + noise * rng.standard_normal(n)
        packets.append({
            "node_id": node_id,
            "window_start_us": t_emit_us + round(start * 1e6),
            "sample_rate_hz": fs,
            "envelope": np.clip(np.round(env), 0, 255).astype(int).tolist(),
        })
    return packets