"""Ocena wytrenowanego modelu na innym datasecie (bez treningu).

Dwa testy:
  * klipy - każde nagranie osobno, okna 1 s co 0.5 s jak na węźle; klip = piła,
    jeśli padł alarm (DETECT_K z DETECT_N okien powyżej progu)
  * miksy - okna syntetyzowane jak w train.py (tło + piła/zdarzenie w losowym SNR)

Ma sens tylko na danych, których model nie widział w treningu, np. model z ESC-50
oceniany na FSC22:
    python evaluate.py --fsc22 data/FSC22 --cache out/fsc22.pkl
"""

import argparse
from pathlib import Path

import numpy as np

import config as C
import datasets as D
import features as F
import plots
from export import TFLiteClassifier
from train import report


def window_feats(audio):
    """Okna 1 s co STREAM_HOP_SEC z jednego klipu, bez profilu tła (brak historii przed klipem)."""
    x = F.highpass(audio.astype(np.float32) / 32767)
    hop = int(C.STREAM_HOP_SEC * C.SAMPLE_RATE)
    if len(x) < C.WINDOW_SAMPLES:
        x = np.pad(x, (0, C.WINDOW_SAMPLES - len(x)))
    return np.stack([F.log_mel(F.mel_power(x[s:s + C.WINDOW_SAMPLES]))
                     for s in range(0, len(x) - C.WINDOW_SAMPLES + 1, hop)])


def alarm_score(p):
    """Największa K-ta wartość w oknie N kolejnych p; >= próg <=> alarm K z N."""
    if len(p) < C.DETECT_N:
        return float(np.sort(p)[-min(C.DETECT_K, len(p))])
    return max(float(np.sort(p[i:i + C.DETECT_N])[-C.DETECT_K])
               for i in range(len(p) - C.DETECT_N + 1))


def eval_clips(clips, clf, out):
    y = np.array([c.label for c in clips], np.float32)
    p_max, p_alarm = [], []
    for i, c in enumerate(clips):
        p = clf(window_feats(c.audio))
        p_max.append(float(p.max()))
        p_alarm.append(alarm_score(p))
        if (i + 1) % 250 == 0:
            print(f"  {i + 1}/{len(clips)} klipów")
    p_max, p_alarm = np.array(p_max), np.array(p_alarm)
    meta = [{"bed": c.category, "fg": None} for c in clips]

    thr = C.DETECT_THRESHOLD
    report("klipy: pojedyncze okno > próg", p_max, y, meta, thr)
    report(f"klipy: alarm {C.DETECT_K} z {C.DETECT_N}", p_alarm, y, meta, thr)

    out.mkdir(parents=True, exist_ok=True)
    results = {"pojedyncze okno": p_max, f"alarm {C.DETECT_K} z {C.DETECT_N}": p_alarm}
    plots.plot_confusion(results, y, thr, out / "confusion_matrix.png")
    plots.plot_roc_pr(results, y, thr, out / "roc_pr.png")
    plots.plot_hist(p_alarm, y, thr, out / "score_hist.png", f"alarm {C.DETECT_K} z {C.DETECT_N}")
    plots.plot_false_alarms(p_alarm, y, meta, thr, out / "false_alarms.png", unit="klipów")
    print(f"Wykresy zapisane w {out}/")


def eval_mixes(clips, clf, keras_path, n, out):
    Xt, yt, mt = D.MixSynth(clips, seed=3).batch(n, with_meta=True)
    p_int8 = clf(Xt)
    report("miksy int8", p_int8, yt, mt, C.DETECT_THRESHOLD)
    if keras_path.exists():
        import keras
        p_float = keras.models.load_model(keras_path).predict(Xt, verbose=0)[:, 0]
        report("miksy float32", p_float, yt, mt, C.DETECT_THRESHOLD)
    else:
        p_float = p_int8
    out.mkdir(parents=True, exist_ok=True)
    np.savez(out / "eval.npz", y=yt, p_float=p_float, p_int8=p_int8,
             meta=np.array(mt, dtype=object))
    plots.save_all(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--esc50", help="katalog ESC-50-master")
    ap.add_argument("--fsc22", help="katalog FSC22")
    ap.add_argument("--folder", action="append", default=[], help="własne nagrania")
    ap.add_argument("--cache", help="plik .pkl z wczytanymi klipami")
    ap.add_argument("--model", default="out/chainsaw_int8.tflite")
    ap.add_argument("--keras", default="out/chainsaw.keras", help="model float (opcjonalnie)")
    ap.add_argument("--n-eval", type=int, default=3000, help="liczba okien w teście miksów")
    ap.add_argument("--out", help="katalog na wyniki (domyślnie out/eval_<dataset>)")
    args = ap.parse_args()

    clips = D.load_all(args.esc50, args.fsc22, args.folder, cache=args.cache)
    name = "_".join(k for k in ("esc50", "fsc22") if getattr(args, k)) or "folder"
    out = Path(args.out or Path(args.model).parent / f"eval_{name}")
    print(f"{len(clips)} klipów, piła: {sum(c.label for c in clips)}")

    clf = TFLiteClassifier(args.model)
    print("\n== Test 1: surowe klipy (detekcja strumieniowa) ==")
    eval_clips(clips, clf, out / "klipy")
    print("\n== Test 2: miksy tło + zdarzenie ==")
    eval_mixes(clips, clf, Path(args.keras), args.n_eval, out / "miksy")


if __name__ == "__main__":
    main()
