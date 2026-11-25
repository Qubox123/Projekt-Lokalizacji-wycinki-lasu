
import logging
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Event, EventStatus, Node

logger = logging.getLogger("lokalizator")


# Siatka w metrach
class LocalFrame:
    """Zamiana (lat, lon) <-> (x, y) w metrach wokół punktu (lat0, lon0).
    Przybliżenie płaskie: przy obszarze kilku km błąd jest pomijalny."""
    M_PER_DEG_LAT = 110_574.0
    M_PER_DEG_LON = 111_320.0  # na równiku; mnożymy przez cos(szerokości)

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = self.M_PER_DEG_LON * math.cos(math.radians(lat0))
        self.ky = self.M_PER_DEG_LAT

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self.ky, self.lon0 + x / self.kx


# Różnica czasu z korelacji obwiedni

def resample(envelope, fs_in: float, fs_out: float) -> np.ndarray:
    """Przelicza obwiednię na inną częstotliwość próbkowania (gdyby węzły miały różne)."""
    env = np.asarray(envelope, dtype=float)
    if fs_in == fs_out:
        return env
    t_in = np.arange(len(env)) / fs_in
    t_out = np.arange(0, len(env) / fs_in, 1 / fs_out)
    return np.interp(t_out, t_in, env)


def measure_tdoa(env_i, start_i_s: float, env_j, start_j_s: float,
                 fs: float, max_dt_s: float) -> tuple[float, float] | None:
    """Zwraca (dt, korelacja), gdzie dt = t_j - t_i: o ile sekund później dźwięk
    dotarł do węzła j niż do węzła i. None, gdy obwiednie są płaskie.
    """
    a = np.asarray(env_i, dtype=float)
    b = np.asarray(env_j, dtype=float)
    a = a - a.mean()
    b = b - b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return None

    corr = np.correlate(b, a, mode="full") / (na * nb)
    lags = np.arange(-(len(a) - 1), len(b))
    offset = start_j_s - start_i_s
    dts = offset + lags / fs

    #  |dt| <= odległość między węzłami / prędkość dźwięku
    allowed = np.abs(dts) <= max_dt_s
    if not allowed.any():
        return None
    k = np.flatnonzero(allowed)[np.argmax(corr[allowed])]

    shift = 0.0
    if 0 < k < len(corr) - 1:
        y0, y1, y2 = corr[k - 1], corr[k], corr[k + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            shift = 0.5 * (y0 - y2) / den
    return offset + (lags[k] + shift) / fs, float(corr[k])



@dataclass
class Solution:
    x: float
    y: float
    radius_m: float
    rms_m: float      # średni błąd w metrach
    ambiguous: bool


def solve_position(xy: np.ndarray, pairs: list[tuple[int, int, float]],
                   c: float, bounds: tuple[float, float, float, float]) -> Solution | None:
    """xy: pozycje węzłów (N x 2) [m]; pairs: lista (i, j, dt) z dt = t_j - t_i;
    bounds: (xmin, ymin, xmax, ymax) obszar szukania."""
    I = np.array([p[0] for p in pairs])
    J = np.array([p[1] for p in pairs])
    measured = c * np.array([p[2] for p in pairs])
    xmin, ymin, xmax, ymax = bounds

    def residuals(p):
        d = np.hypot(p[0] - xy[:, 0], p[1] - xy[:, 1])
        return measured - (d[J] - d[I])

    # liczenie błędu w każdym punkcie

    xs = np.arange(xmin, xmax + config.GRID_STEP_M, config.GRID_STEP_M)
    ys = np.arange(ymin, ymax + config.GRID_STEP_M, config.GRID_STEP_M)
    X, Y = np.meshgrid(xs, ys)
    D = np.hypot(X[..., None] - xy[:, 0], Y[..., None] - xy[:, 1])   # (ny, nx, N)
    cost = np.abs(measured - (D[..., J] - D[..., I])).sum(axis=-1)

    def refine(start):
        start = np.clip(start, [xmin, ymin], [xmax, ymax])   # ostatni punkt siatki może lekko wystawać
        res = least_squares(residuals, start, bounds=([xmin, ymin], [xmax, ymax]),
                            method="trf", loss="huber", f_scale=config.HUBER_SCALE_M)
        rms = float(np.sqrt(np.mean(residuals(res.x) ** 2)))
        return res.x, rms

    iy, ix = np.unravel_index(np.argmin(cost), cost.shape)
    best_p, best_rms = refine([X[iy, ix], Y[iy, ix]])

    # Przy 3 węzłach mogą istnieć DWA punkty pasujące do pomiarów.
    # Sprawdzamy najlepszy punkt siatki daleko od pierwszego rozwiązania.
    ambiguous = False
    far = np.hypot(X - best_p[0], Y - best_p[1]) > config.AMBIGUITY_DIST_M
    if far.any():
        masked = np.where(far, cost, np.inf)
        jy, jx = np.unravel_index(np.argmin(masked), cost.shape)
        p2, rms2 = refine([X[jy, jx], Y[jy, jx]])
        distinct = np.hypot(*(p2 - best_p)) > config.AMBIGUITY_DIST_M
        if distinct and rms2 <= best_rms + 1.0:
            ambiguous = True
            center = xy.mean(axis=0)
            if np.hypot(*(p2 - center)) < np.hypot(*(best_p - center)):
                best_p, best_rms = p2, rms2

    edge = config.GRID_STEP_M
    if not (xmin + edge < best_p[0] < xmax - edge and ymin + edge < best_p[1] < ymax - edge):
        return None

    # liczenie niepewności
    d = np.hypot(best_p[0] - xy[:, 0], best_p[1] - xy[:, 1])
    u = (best_p - xy) / d[:, None]
    jac = -(u[J] - u[I])
    sigma_m = c * config.TDOA_SIGMA_S
    cov = sigma_m ** 2 * np.linalg.pinv(jac.T @ jac)
    radius = 2 * math.sqrt(max(float(np.trace(cov)), 0.0))
    if ambiguous:
        radius = max(radius, config.AMBIGUITY_DIST_M)

    return Solution(float(best_p[0]), float(best_p[1]), radius, best_rms, ambiguous)



def localize_event(db: Session, event: Event) -> None:
    """Liczy pozycję zdarzenia i zapisuje wynik w obiekcie event"""
    packets = sorted(event.packets, key=lambda p: p.node_id)
    ids = [p.node_id for p in packets]
    nodes = {n.node_id: n for n in db.scalars(select(Node).where(Node.node_id.in_(ids)))}

    frame = LocalFrame(np.mean([nodes[i].lat for i in ids]), np.mean([nodes[i].lon for i in ids]))
    xy = np.array([frame.to_xy(nodes[i].lat, nodes[i].lon) for i in ids])

    fs = max(p.sample_rate_hz for p in packets)
    envs = [resample(p.envelope, p.sample_rate_hz, fs) for p in packets]
    t_ref = min(p.window_start_us for p in packets)
    starts = [(p.window_start_us - t_ref) / 1e6 for p in packets]   # [s] od najwcześniejszego okna
    c = config.SPEED_OF_SOUND

    pairs = []
    for i in range(len(packets)):
        for j in range(i + 1, len(packets)):
            max_dt = np.hypot(*(xy[j] - xy[i])) / c + config.TDOA_MARGIN_S
            m = measure_tdoa(envs[i], starts[i], envs[j], starts[j], fs, max_dt)
            if m is None or m[1] < config.MIN_CORRELATION:
                logger.info("Zdarzenie %s: para %s-%s odrzucona (%s)", event.id, ids[i], ids[j], m)
                continue
            pairs.append((i, j, m[0]))

    if len(pairs) < 2:
        logger.warning("Zdarzenie %s: za mało wiarygodnych różnic czasu", event.id)
        event.status = EventStatus.FAILED
        return

    m = config.SEARCH_MARGIN_M
    bounds = (xy[:, 0].min() - m, xy[:, 1].min() - m, xy[:, 0].max() + m, xy[:, 1].max() + m)
    sol = solve_position(xy, pairs, c, bounds)
    if sol is None:
        logger.warning("Zdarzenie %s: rozwiązanie poza obszarem szukania", event.id)
        event.status = EventStatus.FAILED
        return

    event.lat, event.lon = frame.to_latlon(sol.x, sol.y)
    event.accuracy_m = round(sol.radius_m, 1)
    event.status = EventStatus.LOCALIZED
    if sol.ambiguous:
        logger.warning("Zdarzenie %s: dwa możliwe położenia, wybrano bliższe środka", event.id)