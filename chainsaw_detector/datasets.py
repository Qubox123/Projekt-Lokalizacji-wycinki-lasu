"""Wczytywanie datasetów i synteza przykładów treningowych.

Obsługiwane źródła:
  * ESC-50  (https://github.com/karolpiczak/ESC-50)  - klasa "chainsaw" + 49 innych
  * FSC22   (Forest Sound Classification, Kaggle)    - klasa "Chainsaw" + dźwięki lasu
  * manifest - unified_dataset/manifest_eligible.csv (Kenya, FrugalAI, Zenodo)
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


def load_manifest(manifest, cache_dir=None, min_sec=0.5):
    """unified_dataset/manifest_eligible.csv: jawne label, group_id, ścieżki względne.

    Cały zbiór to ok. 43 h (ok. 5 GB int16 po 16 kHz), więc audio trafia do jednego
    pliku .npy otwieranego jako memmap - czytane są tylko potrzebne wycinki.
    """
    manifest = Path(manifest)
    root = manifest.parent
    with open(manifest, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if r.get("eligible_for_training", "1") == "1"
                and float(r["duration_seconds"]) >= min_sec]

    cache_dir = Path(cache_dir or root)
    audio_path, meta_path = cache_dir / "manifest_audio.npy", cache_dir / "manifest_meta.pkl"
    if not (audio_path.exists() and meta_path.exists()):
        cache_dir.mkdir(parents=True, exist_ok=True)
        est = sum(math.ceil(int(r["n_frames"]) * C.SAMPLE_RATE / int(r["sample_rate"])) + 16
                  for r in rows)
        buf = np.lib.format.open_memmap(audio_path, mode="w+", dtype=np.int16, shape=(est,))
        meta, pos = [], 0
        for i, r in enumerate(rows):
            x = to_int16(load_audio(root / r["path"]))
            buf[pos:pos + len(x)] = x
            meta.append((pos, len(x), int(r["label"]),
                         f"{r['dataset']}:{_norm(r['original_label'] or r['category'])}",
                         r["group_id"], r["dataset"]))
            pos += len(x)
            if (i + 1) % 2000 == 0:
                print(f"  wczytano {i + 1}/{len(rows)} plików")
        buf.flush()
        del buf
        with open(meta_path, "wb") as f:
            pickle.dump(meta, f)

    audio = np.load(audio_path, mmap_mode="r")
    with open(meta_path, "rb") as f:
        meta = pickle.load(f)
    return [Clip(audio[o:o + n], label, cat, group, src)
            for o, n, label, cat, group, src in meta]


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


def load_all(esc50=None, fsc22=None, folders=(), synthetic=False, cache=None,
              manifest=None, manifest_cache=None):
    """`cache` (.pkl) obejmuje ESC-50/FSC22/foldery; manifest ma własny cache memmap."""
    if cache and Path(cache).exists():
        with open(cache, "rb") as f:
            clips = pickle.load(f)
    else:
        clips = []
        if esc50:
            clips += load_esc50(esc50)
        if fsc22:
            clips += load_fsc22(fsc22)
        for folder in folders:
            clips += load_folder(folder)
        if synthetic:
            clips += make_synthetic()
        if cache and clips:
            Path(cache).parent.mkdir(parents=True, exist_ok=True)
            with open(cache, "wb") as f:
                pickle.dump(clips, f, protocol=5)
    if manifest:
        clips += load_manifest(manifest, manifest_cache)
    if not clips:
        raise SystemExit("Nie podano żadnego datasetu "
                         "(--esc50 / --fsc22 / --folder / --manifest / --synthetic)")
    return clips


def split_by_group(clips, val=0.1, test=0.1, max_ratio=2.0):
    """Deterministyczny podział po nagraniu źródłowym, osobno dla każdego źródła.

    Cała grupa (nagranie) trafia do jednego zbioru, więc nie ma przecieku. Dla każdego
    źródła najpierw dajemy do test i val po jednej grupie z piłą (jeśli są), potem
    dopełniamy do docelowego ułamka. Grupy większe niż max_ratio * cel zostają w train,
    żeby np. jedno długie nagranie z Kenii nie zabrało całej piły z treningu.
    """
    by_source = {}
    for c in clips:
        by_source.setdefault(c.source, {}).setdefault(c.group, []).append(c)
    parts = {"train": [], "val": [], "test": []}
    targets = (("test", test), ("val", val))
    for groups in by_source.values():
        order = sorted(groups, key=lambda g: zlib.crc32(g.encode()))
        npos = {g: sum(c.label for c in groups[g]) for g in order}
        tot = {"pos": sum(npos.values()),
               "neg": sum(len(groups[g]) for g in order if not npos[g])}
        taken = {name: {"pos": 0, "neg": 0} for name, _ in targets}
        dest = {}

        def size(g):
            return ("pos", npos[g]) if npos[g] else ("neg", len(groups[g]))

        def fits(name, frac, g):
            kind, n = size(g)
            return taken[name][kind] + n <= max(max_ratio * frac * tot[kind], 1)

        for name, frac in targets:            # 1) po jednej grupie z piłą do test i val
            for g in order:
                if npos[g] and g not in dest and fits(name, frac, g):
                    dest[g] = name
                    taken[name]["pos"] += npos[g]
                    break
        for g in order:                       # 2) dopełnienie do docelowego ułamka
            if g in dest:
                continue
            kind, n = size(g)
            dest[g] = "train"
            for name, frac in targets:
                if taken[name][kind] < frac * tot[kind] and fits(name, frac, g):
                    dest[g] = name
                    taken[name][kind] += n
                    break
        for g in order:
            parts[dest[g]].extend(groups[g])
    return parts


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-9)


class _SourcePool:
    """Losowanie: najpierw źródło (waga n**alpha), potem klip z tego źródła.

    alpha=1 to zwykłe losowanie po klipach (FrugalAI ok. 97% pił), alpha=0 to równo
    po źródłach (108 klipów z Kenii dostałoby tyle samo co 17 tys. z FrugalAI
    i model zapamiętałby jedno nagranie). Domyślne 0.3 jest pomiędzy.
    """

    def __init__(self, clips, alpha):
        by = {}
        for c in clips:
            by.setdefault(c.source, []).append(c)
        self.sources = sorted(by)
        self.clips = [by[s] for s in self.sources]
        w = np.array([len(c) ** alpha for c in self.clips], np.float64)
        self.p = w / w.sum()

    def __len__(self):
        return sum(len(c) for c in self.clips)

    def draw(self, rng):
        group = self.clips[rng.choice(len(self.clips), p=self.p)]
        return group[rng.integers(len(group))]

    def describe(self):
        return ", ".join(f"{s} {p:.0%}" for s, p in zip(self.sources, self.p))


class MixSynth:
    """Generuje 1 s okna: tło + piła / inne zdarzenie / nic."""

    def __init__(self, clips, seed=0, p_pos=0.5, p_neg_event=0.5, p_quiet_bed=0.15,
                 snr_db=(-10.0, 20.0), level_db=(-65.0, -10.0), p_band_limit=0.3,
                 p_distance=0.6, distance_hz=(800.0, 7000.0), p_raw=0.2, source_alpha=0.3):
        self.rng = np.random.default_rng(seed)
        self.pos = _SourcePool([c for c in clips if c.label == 1], source_alpha)
        self.neg = _SourcePool([c for c in clips if c.label == 0], source_alpha)
        if not len(self.pos) or not len(self.neg):
            raise ValueError(f"Potrzebne oba rodzaje klipów (piła: {len(self.pos)}, inne: {len(self.neg)})")
        self.p_pos, self.p_neg_event, self.p_quiet_bed = p_pos, p_neg_event, p_quiet_bed
        self.snr_db, self.level_db = snr_db, level_db
        self.p_band_limit, self.p_distance, self.distance_hz = p_band_limit, p_distance, distance_hz
        self.p_raw = p_raw

    def _crop(self, clip, n, energetic=False):
        x = clip.audio
        if len(x) < n:
            # dopełnienie ciszą w losowym miejscu, bez zapętlania krótkich klipów
            s = self.rng.integers(0, n - len(x) + 1)
            x = np.pad(np.asarray(x), (s, n - len(x) - s))
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
        lo, hi = np.log(self.distance_hz)
        fc = np.exp(self.rng.uniform(lo, hi))   # log-równomiernie: 800 Hz ... 7 kHz
        return signal.sosfilt(signal.butter(2, fc, "lp", fs=C.SAMPLE_RATE, output="sos"), x)

    def sample(self):
        rng, n = self.rng, C.WINDOW_SAMPLES
        label = int(rng.random() < self.p_pos)

        if label and rng.random() < self.p_raw:
            # nagranie piły bez dokładanego tła - nagrania terenowe (Kenia, Zenodo) mają
            # już własne tło, a dokładanie kolejnego potrafi całkiem zakryć daleką piłę
            fg_clip = self.pos.draw(rng)
            mix = self._crop(fg_clip, n, energetic=True)
            return self._finish(mix, None, label, {"bed": None, "fg": fg_clip.category,
                                                   "src": fg_clip.source})

        if rng.random() < self.p_quiet_bed:
            # cichy las: lekko kolorowany szum
            w = signal.lfilter([1], [1, -rng.uniform(0, 0.95)], rng.standard_normal(2 * n))
            seg, bed_cat = (w / _rms(w) * 1e-3).astype(np.float32), "quiet"
        else:
            bed_clip = self.neg.draw(rng)
            seg, bed_cat = self._crop(bed_clip, 2 * n), bed_clip.category
        ref, bed = seg[:n], seg[n:]           # ref = tło przed oknem
        mix, fg_cat = bed.copy(), None
        src = "quiet" if bed_cat == "quiet" else bed_clip.source

        fg = None
        if label:
            fg_clip = self.pos.draw(rng)
            fg = self._crop(fg_clip, n, energetic=True)
            if rng.random() < self.p_distance:
                fg = self._distance_lowpass(fg)
        elif rng.random() < self.p_neg_event:
            fg_clip = self.neg.draw(rng)
            fg = self._crop(fg_clip, n, energetic=True)
        if fg is not None:
            snr = rng.uniform(*self.snr_db)
            mix = mix + fg * (_rms(bed) * 10 ** (snr / 20) / _rms(fg))
            fg_cat = fg_clip.category
            if label:
                src = fg_clip.source
        return self._finish(mix, ref, label, {"bed": bed_cat, "fg": fg_cat, "src": src})

    def _finish(self, mix, ref, label, meta):
        """Obcięcie pasma, losowa głośność, profil tła i cechy."""
        rng = self.rng

        if rng.random() < self.p_band_limit:
            # część nagrań ma 8/12 kHz (pasmo do 4/6 kHz) - obcinamy pasmo całego miksu
            # niezależnie od etykiety, żeby szerokość pasma nie zdradzała klasy
            sos = signal.butter(4, rng.uniform(3500, 6000), "lp", fs=C.SAMPLE_RATE, output="sos")
            mix = signal.sosfilt(sos, mix)
            if ref is not None:
                ref = signal.sosfilt(sos, ref)

        gain = 10 ** (rng.uniform(*self.level_db) / 20) / _rms(mix)
        mix = np.clip(mix * gain, -1, 1)
        profile = None
        if ref is not None and rng.random() < 0.9:
            profile = F.noise_profile(np.clip(ref * gain, -1, 1))
        feats = F.extract_features(mix.astype(np.float32), profile)
        return feats, label, meta

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
