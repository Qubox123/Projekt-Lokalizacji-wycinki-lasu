"""Wczytywanie datasetów i synteza przykładów treningowych.

Obsługiwane źródła:
  * ESC-50  (https://github.com/karolpiczak/ESC-50)  - klasa "chainsaw" + 49 innych
  * FSC22   (Forest Sound Classification, Kaggle)    - klasa "Chainsaw" + dźwięki lasu
  * folder  - własne nagrania: <root>/chainsaw/*.wav oraz <root>/<dowolna_klasa>/*.wav
  * synthetic - sztuczne dźwięki do szybkiego sprawdzenia, że potok działa

Przykład treningowy to 1 s okno: tło (deszcz, wiatr, ptaki...) + opcjonalnie
piła albo inne zdarzenie w losowym SNR. Profil szumu dla odejmowania widmowego
liczony jest z fragmentu tła PRZED oknem, tak jak robi to węzeł w lesie.
"""

import csv
import math
import pickle
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

import config as C
import features as F


@dataclass
class Clip:
    audio: np.ndarray   # int16, mono, SAMPLE_RATE
    label: int          # 1 = piła
    category: str
    group: str          # nagranie źródłowe; podział train/val/test idzie po grupach
    source: str


def load_audio(path, sr=C.SAMPLE_RATE):
    data, fs = sf.read(str(path), dtype="float32", always_2d=True)
    x = data.mean(axis=1)
    if fs != sr:
        g = math.gcd(int(fs), sr)
        x = signal.resample_poly(x, sr // g, int(fs) // g)
    return x.astype(np.float32)


def to_int16(x):
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)


def _norm(name):
    return name.strip().lower().replace(" ", "").replace("_", "")


def load_esc50(root, positive=("chainsaw",)):
    root = Path(root)
    clips = []
    with open(root / "meta" / "esc50.csv", newline="") as f:
        for row in csv.DictReader(f):
            cat = _norm(row["category"])
            clips.append(Clip(to_int16(load_audio(root / "audio" / row["filename"])),
                              int(cat in positive), cat,
                              f"esc50:{row['src_file']}", "esc50"))
    return clips


def load_fsc22(root, positive=("chainsaw",)):
    root = Path(root)
    meta = sorted(root.rglob("*.csv"))
    if not meta:
        raise FileNotFoundError(f"Brak pliku metadanych *.csv w {root}")
    wavs = {p.name: p for p in root.rglob("*.wav")}
    clips = []
    with open(meta[0], newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {_norm(k): v for k, v in row.items()}
            name = row.get("datasetfilename") or row.get("filename")
            path = wavs.get(name)
            if path is None:
                continue
            cat = _norm(row["classname"])
            src = row.get("sourcefilename", name)
            clips.append(Clip(to_int16(load_audio(path)), int(cat in positive), cat,
                              f"fsc22:{src}", "fsc22"))
    return clips


def load_folder(root, positive=("chainsaw",)):
    """<root>/chainsaw/*.wav -> piła, każdy inny podfolder -> tło/inne."""
    root = Path(root)
    clips = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in (".wav", ".flac", ".ogg"):
            continue
        cat = _norm(path.relative_to(root).parts[0])
        clips.append(Clip(to_int16(load_audio(path)), int(cat in positive), cat,
                          f"folder:{path.relative_to(root)}", "folder"))
    return clips


def make_synthetic(n_per_class=40, dur=5.0, seed=0):
    """Sztuczne dźwięki - tylko do testu potoku, nie do prawdziwego modelu."""
    rng = np.random.default_rng(seed)
    sr, n = C.SAMPLE_RATE, int(dur * C.SAMPLE_RATE)
    t = np.arange(n) / sr
    clips = []

    def add(x, label, cat, i):
        x = 0.7 * x / (np.abs(x).max() + 1e-9)
        clips.append(Clip(to_int16(x), label, cat, f"synth:{cat}:{i}", "synthetic"))

    for i in range(n_per_class):
        # piła: ton podstawowy 90-220 Hz z dryfem obrotów + harmoniczne + szum spalania
        f0 = rng.uniform(90, 220) * (1 + 0.15 * np.sin(2 * np.pi * rng.uniform(0.1, 0.5) * t
                                                       + rng.uniform(0, 6)))
        phase = 2 * np.pi * np.cumsum(f0) / sr
        tilt = rng.uniform(0.6, 1.2)
        x = sum(k ** -tilt * np.sin(k * phase + rng.uniform(0, 6)) for k in range(1, 28))
        x = x + 0.3 * rng.standard_normal(n) * (1 + np.sin(phase))
        add(x, 1, "chainsaw", i)

        # deszcz: szum górnopasmowy + krople (krótkie zanikające impulsy)
        rain = signal.sosfilt(signal.butter(2, rng.uniform(500, 2000), "hp", fs=sr, output="sos"),
                              rng.standard_normal(n))
        drops = np.zeros(n)
        drops[rng.integers(0, n, int(rng.uniform(50, 400) * dur))] = rng.uniform(1, 5)
        drops = signal.lfilter([1], [1, -0.95], drops) * rng.standard_normal(n)
        add(rain + 0.5 * drops, 0, "rain", i)

        # wiatr i szum liści: niskopasmowy szum z podmuchami + szelest 2-6 kHz
        gust = 1 + 0.8 * np.sin(2 * np.pi * rng.uniform(0.05, 0.4) * t + rng.uniform(0, 6))
        low = signal.sosfilt(signal.butter(2, 400, "lp", fs=sr, output="sos"), rng.standard_normal(n))
        leaves = signal.sosfilt(signal.butter(2, [2000, 6000], "bp", fs=sr, output="sos"),
                                rng.standard_normal(n))
        add(gust * (low + rng.uniform(0.1, 0.6) * leaves), 0, "wind", i)

        # ptaki: seria ćwierknięć z modulacją częstotliwości 2-7 kHz
        birds = np.zeros(n)
        for _ in range(rng.integers(4, 15)):
            s, L = rng.integers(0, n - 4000), rng.integers(800, 4000)
            tt = np.arange(L) / sr
            f = rng.uniform(2000, 6000) + rng.uniform(-1500, 1500) * tt / tt[-1]
            birds[s:s + L] += np.sin(2 * np.pi * np.cumsum(f) / sr) * np.hanning(L)
        add(birds + 0.05 * rng.standard_normal(n), 0, "birds", i)

        # świerszcze: ton ~4-5 kHz impulsowany ~30 Hz
        fc, rate = rng.uniform(3500, 5500), rng.uniform(15, 40)
        add(np.sin(2 * np.pi * fc * t) * (np.sin(2 * np.pi * rate * t) > 0.3)
            + 0.05 * rng.standard_normal(n), 0, "insects", i)
    return clips


def load_all(esc50=None, fsc22=None, folders=(), synthetic=False, cache=None):
    if cache and Path(cache).exists():
        with open(cache, "rb") as f:
            return pickle.load(f)
    clips = []
    if esc50:
        clips += load_esc50(esc50)
    if fsc22:
        clips += load_fsc22(fsc22)
    for folder in folders:
        clips += load_folder(folder)
    if synthetic:
        clips += make_synthetic()
    if not clips:
        raise SystemExit("Nie podano żadnego datasetu (--esc50 / --fsc22 / --folder / --synthetic)")
    if cache:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "wb") as f:
            pickle.dump(clips, f, protocol=5)
    return clips


def split_by_group(clips, val=0.1, test=0.1):
    """Deterministyczny podział po nagraniu źródłowym (bez przecieku między zbiorami)."""
    parts = {"train": [], "val": [], "test": []}
    for c in clips:
        u = zlib.crc32(c.group.encode()) / 2 ** 32
        parts["test" if u < test else "val" if u < test + val else "train"].append(c)
    return parts


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-9)


class MixSynth:
    """Generuje 1 s okna: tło + piła / inne zdarzenie / nic."""

    def __init__(self, clips, seed=0, p_pos=0.5, p_neg_event=0.5, p_quiet_bed=0.15,
                 snr_db=(-5.0, 20.0), level_db=(-45.0, -10.0)):
        self.rng = np.random.default_rng(seed)
        self.pos = [c for c in clips if c.label == 1]
        self.neg = [c for c in clips if c.label == 0]
        if not self.pos or not self.neg:
            raise ValueError(f"Potrzebne oba rodzaje klipów (piła: {len(self.pos)}, inne: {len(self.neg)})")
        self.p_pos, self.p_neg_event, self.p_quiet_bed = p_pos, p_neg_event, p_quiet_bed
        self.snr_db, self.level_db = snr_db, level_db

    def _crop(self, clip, n, energetic=False):
        x = clip.audio
        if len(x) < n:
            x = np.resize(x, n)   # zapętlenie krótkiego klipu
        best, best_rms = None, -1.0
        for _ in range(6 if energetic else 1):   # unikaj wycinków z ciszą
            s = self.rng.integers(0, len(x) - n + 1)
            seg = x[s:s + n].astype(np.float32) / 32767
            r = _rms(seg)
            if r > best_rms:
                best, best_rms = seg, r
        return best

    def _distance_lowpass(self, x):
        """Pochłanianie wysokich częstotliwości przez powietrze i las na dystansie."""
        fc = self.rng.uniform(2000, 7000)
        return signal.sosfilt(signal.butter(2, fc, "lp", fs=C.SAMPLE_RATE, output="sos"), x)

    def sample(self):
        rng, n = self.rng, C.WINDOW_SAMPLES
        label = int(rng.random() < self.p_pos)

        if rng.random() < self.p_quiet_bed:
            # cichy las: lekko kolorowany szum
            w = signal.lfilter([1], [1, -rng.uniform(0, 0.95)], rng.standard_normal(2 * n))
            seg, bed_cat = (w / _rms(w) * 1e-3).astype(np.float32), "quiet"
        else:
            bed_clip = self.neg[rng.integers(len(self.neg))]
            seg, bed_cat = self._crop(bed_clip, 2 * n), bed_clip.category
        ref, bed = seg[:n], seg[n:]           # ref = tło przed oknem
        mix, fg_cat = bed.copy(), None

        fg = None
        if label:
            fg_clip = self.pos[rng.integers(len(self.pos))]
            fg = self._crop(fg_clip, n, energetic=True)
            if rng.random() < 0.5:
                fg = self._distance_lowpass(fg)
        elif rng.random() < self.p_neg_event:
            fg_clip = self.neg[rng.integers(len(self.neg))]
            fg = self._crop(fg_clip, n, energetic=True)
        if fg is not None:
            snr = rng.uniform(*self.snr_db)
            mix = mix + fg * (_rms(bed) * 10 ** (snr / 20) / _rms(fg))
            fg_cat = fg_clip.category

        gain = 10 ** (rng.uniform(*self.level_db) / 20) / _rms(mix)
        mix = np.clip(mix * gain, -1, 1)
        ref = np.clip(ref * gain, -1, 1)
        profile = F.noise_profile(ref) if rng.random() < 0.9 else None
        feats = F.extract_features(mix.astype(np.float32), profile)
        return feats, label, {"bed": bed_cat, "fg": fg_cat}

    def batch(self, size, with_meta=False):
        out = [self.sample() for _ in range(size)]
        X = np.stack([o[0] for o in out])[..., None]
        y = np.array([o[1] for o in out], np.float32)
        return (X, y, [o[2] for o in out]) if with_meta else (X, y)

    def spec_augment(self, X):
        """Losowe maskowanie pasm i ramek (SpecAugment-lite)."""
        X = X.copy()
        fill = X.min()
        for x in X:
            if self.rng.random() < 0.5:
                f0, w = self.rng.integers(0, C.N_MELS - 6), self.rng.integers(1, 6)
                x[:, f0:f0 + w] = fill
            if self.rng.random() < 0.5:
                t0, w = self.rng.integers(0, C.N_FRAMES - 8), self.rng.integers(1, 8)
                x[t0:t0 + w] = fill
        return X
