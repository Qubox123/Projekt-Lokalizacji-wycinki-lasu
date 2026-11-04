"""Trening detektora piły mechanicznej.

Przykłady:
    python train.py --synthetic --epochs 3                       # test potoku
    python train.py --esc50 data/ESC-50-master --fsc22 data/FSC22
    python train.py --fsc22 data/FSC22 --folder data/nagrania_z_lasu
    python train.py --esc50 data/ESC-50-master --fsc22 data/FSC22 --cache out/clips.pkl \
        --manifest unified_dataset/manifest_eligible.csv
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import keras
import numpy as np

import config as C
import datasets as D
import export as E
import plots
from model import build_model


class TrainSequence(keras.utils.PyDataset):
    """Każdy batch syntetyzowany na nowo -> praktycznie nieskończona augmentacja."""

    def __init__(self, synth, batch_size, steps):
        super().__init__()
        self.synth, self.batch_size, self.steps = synth, batch_size, steps

    def __len__(self):
        return self.steps

    def __getitem__(self, idx):
        X, y = self.synth.batch(self.batch_size)
        return self.synth.spec_augment(X), y


def report(name, p, y, meta, thr):
    pred = p >= thr
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    print(f"\n[{name}] próg={thr:.2f}  acc={(tp + tn) / len(y):.3f}  "
          f"precision={tp / max(tp + fp, 1):.3f}  recall={tp / max(tp + fn, 1):.3f}")
    print(f"  macierz pomyłek: TP={tp} FN={fn} | FP={fp} TN={tn}")
    # które dźwięki tła są mylone z piłą
    fps, total = defaultdict(int), Counter()
    for pi, yi, m in zip(pred, y, meta):
        if yi == 0:
            for cat in {m["bed"], m["fg"]} - {None}:
                total[cat] += 1
                fps[cat] += int(pi)
    worst = sorted(total, key=lambda c: -fps[c] / total[c])[:8]
    print("  najczęstsze fałszywe alarmy:",
          ", ".join(f"{c} {fps[c]}/{total[c]}" for c in worst if fps[c]) or "brak")
    if meta and "src" in meta[0]:
        # piła: źródło nagrania piły; inne: źródło tła
        hit, n = defaultdict(int), Counter()
        for pi, yi, m in zip(pred, y, meta):
            n[(m["src"], int(yi))] += 1
            hit[(m["src"], int(yi))] += int(pi)
        print("  wg źródła:")
        for src in sorted({k[0] for k in n}):
            pos, neg = (src, 1), (src, 0)
            line = f"    {src:9s}"
            if n[pos]:
                line += f"  piła wykryta {hit[pos]}/{n[pos]} = {hit[pos] / n[pos]:.1%}"
            if n[neg]:
                line += f"  fałszywe alarmy {hit[neg]}/{n[neg]} = {hit[neg] / n[neg]:.1%}"
            print(line)


def clip_report(clips, clf, max_per_class=600, seed=0):
    """Surowe nagrania testowe, okna 1 s co 0.5 s, alarm K z N - jak węzeł, bez miksowania."""
    from evaluate import alarm_score, window_feats   # import tutaj: evaluate importuje train

    rng = np.random.default_rng(seed)
    by = defaultdict(list)
    for c in clips:
        by[(c.source, c.label)].append(c)
    print(f"\n[test: surowe nagrania, alarm {C.DETECT_K} z {C.DETECT_N}, próg {C.DETECT_THRESHOLD}]")
    result = {}
    for (src, label), cs in sorted(by.items()):
        if len(cs) > max_per_class:
            cs = [cs[i] for i in rng.choice(len(cs), max_per_class, replace=False)]
        alarms = sum(alarm_score(clf(window_feats(np.asarray(c.audio)))) >= C.DETECT_THRESHOLD
                     for c in cs)
        what = "piła wykryta" if label else "fałszywe alarmy"
        print(f"  {src:9s} {what:16s} {alarms}/{len(cs)} = {alarms / len(cs):.1%}")
        result[f"{src}:{'pila' if label else 'inne'}"] = [int(alarms), len(cs)]
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--esc50", help="katalog ESC-50-master (z meta/ i audio/)")
    ap.add_argument("--fsc22", help="katalog FSC22 (wav + csv z metadanymi)")
    ap.add_argument("--folder", action="append", default=[],
                    help="własne nagrania: <dir>/chainsaw/*.wav, <dir>/<inne>/*.wav")
    ap.add_argument("--manifest", help="unified_dataset/manifest_eligible.csv (label, group_id)")
    ap.add_argument("--manifest-cache", default="out/manifest_cache",
                    help="katalog na audio z manifestu jako memmap (ok. 5 GB)")
    ap.add_argument("--synthetic", action="store_true", help="dodaj sztuczne dźwięki (test)")
    ap.add_argument("--cache", help="plik .pkl z wczytanymi klipami (przyspiesza kolejne uruchomienia)")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--n-eval", type=int, default=3000)
    ap.add_argument("--width", type=int, default=16)
    ap.add_argument("--source-alpha", type=float, default=0.3,
                    help="waga źródła = liczba_klipów**alpha (0 = równo po źródłach, 1 = po klipach)")
    ap.add_argument("--out", default="out")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    keras.utils.set_random_seed(args.seed)

    clips = D.load_all(args.esc50, args.fsc22, args.folder, args.synthetic, args.cache,
                       args.manifest, args.manifest_cache)
    parts = D.split_by_group(clips)
    for k, v in parts.items():
        per_src = Counter((c.source, c.label) for c in v)
        print(f"{k:5s}: {len(v)} klipów, piła: {sum(c.label for c in v)}  |  " + ", ".join(
            f"{s} {per_src[(s, 1)]}/{per_src[(s, 0)]}" for s in sorted({s for s, _ in per_src})))
    print("       (źródło piła/inne)")

    alpha = args.source_alpha
    train_synth = D.MixSynth(parts["train"], seed=args.seed, source_alpha=alpha)
    print("losowanie piły:", train_synth.pos.describe())
    print("losowanie tła: ", train_synth.neg.describe())
    Xv, yv, mv = D.MixSynth(parts["val"], seed=1, source_alpha=alpha).batch(args.n_eval, with_meta=True)
    Xt, yt, mt = D.MixSynth(parts["test"], seed=2, source_alpha=alpha).batch(args.n_eval, with_meta=True)

    Xn, _ = train_synth.batch(2000)
    mel_mean = Xn.mean(axis=(0, 1, 3))
    mel_var = Xn.var(axis=(0, 1, 3)) + 1e-6

    model = build_model(mel_mean, mel_var, width=args.width)
    model.summary()
    model.compile(optimizer=keras.optimizers.Adam(1e-3),
                  loss="binary_crossentropy",
                  metrics=["binary_accuracy", keras.metrics.AUC(name="auc"),
                           keras.metrics.Precision(name="precision"),
                           keras.metrics.Recall(name="recall")])
    hist = model.fit(TrainSequence(train_synth, args.batch, args.steps),
              validation_data=(Xv, yv), epochs=args.epochs,
              callbacks=[
                  keras.callbacks.EarlyStopping("val_auc", mode="max", patience=8,
                                                restore_best_weights=True),
                  keras.callbacks.ReduceLROnPlateau("val_loss", factor=0.5, patience=3),
              ])
    model.save(out / "chainsaw.keras")

    p_float = model.predict(Xt, verbose=0)[:, 0]
    report("test float32", p_float, yt, mt, C.DETECT_THRESHOLD)

    tflite = E.to_tflite_int8(model, Xn[:500])
    (out / "chainsaw_int8.tflite").write_bytes(tflite)
    clf = E.TFLiteClassifier(tflite)
    p_int8 = clf(Xt)
    report("test int8 (jak na ESP32)", p_int8, yt, mt, C.DETECT_THRESHOLD)

    clip_results = clip_report(parts["test"], clf)
    (out / "clips_by_source.json").write_text(json.dumps(clip_results, indent=1))

    E.write_model_header(tflite, out / "chainsaw_model_data.h")
    E.write_feature_header(out / "feature_config.h", clf)
    (out / "history.json").write_text(json.dumps(
        {k: [float(v) for v in vals] for k, vals in hist.history.items()}, indent=1))
    np.savez(out / "eval.npz", y=yt, p_float=p_float, p_int8=p_int8,
             meta=np.array(mt, dtype=object))
    plots.save_all(out)

    print(f"\nModel int8: {len(tflite) / 1024:.1f} KB, parametry: {model.count_params()}")
    print(f"Zapisano do {out}/: chainsaw.keras, chainsaw_int8.tflite, "
          "chainsaw_model_data.h, feature_config.h")


if __name__ == "__main__":
    main()
