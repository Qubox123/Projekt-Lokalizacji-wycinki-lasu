"""Wizualizacja wyników treningu.

train.py zapisuje out/history.json i out/eval.npz, a potem woła save_all().
Wykresy można też odtworzyć bez ponownego treningu:
    python plots.py out
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import MaxNLocator

import config as C

BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e6e5e1", "#fcfcfb"
SEQ_BLUE = LinearSegmentedColormap.from_list(
    "seq_blue", ["#f3f8fe", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "lines.linewidth": 2, "legend.frameon": False, "legend.labelcolor": INK2,
    "font.size": 10, "savefig.dpi": 150, "savefig.bbox": "tight",
})


def confusion(p, y, thr):
    pred = p >= thr
    return np.array([[int((~pred & (y == 0)).sum()), int((pred & (y == 0)).sum())],
                     [int((~pred & (y == 1)).sum()), int((pred & (y == 1)).sum())]])


def roc_pr(p, y):
    """Krzywe ROC i precision-recall bez sklearn."""
    order = np.argsort(-p, kind="stable")
    ys = y[order]
    tp, fp = np.cumsum(ys), np.cumsum(1 - ys)
    P, N = max(ys.sum(), 1), max(len(ys) - ys.sum(), 1)
    tpr, fpr = np.r_[0, tp / P], np.r_[0, fp / N]
    prec = np.r_[1, tp / np.maximum(tp + fp, 1)]
    auc = float(np.trapezoid(tpr, fpr))
    ap = float(np.sum(np.diff(tpr) * prec[1:]))
    return fpr, tpr, prec, auc, ap


def plot_history(history, path):
    panels = [("loss", "Strata (loss)"), ("auc", "AUC"),
              ("precision", "Precision"), ("recall", "Recall")]
    panels = [(k, t) for k, t in panels if k in history]
    fig, axes = plt.subplots(1, len(panels), figsize=(4 * len(panels), 3.4))
    axes = np.atleast_1d(axes)
    for ax, (key, title) in zip(axes, panels):
        ep = np.arange(1, len(history[key]) + 1)
        ax.plot(ep, history[key], color=BLUE, label="train")
        if f"val_{key}" in history:
            val = history[f"val_{key}"]
            ax.plot(ep, val, color=ORANGE, label="val")
            best = int(np.argmin(val) if key == "loss" else np.argmax(val))
            ax.scatter(ep[best], val[best], s=40, color=ORANGE, edgecolor=SURFACE,
                       linewidth=2, zorder=3)
            lo, hi = ax.get_ylim() if key == "loss" else (0, 1.05)
            above = val[best] < lo + 0.85 * (hi - lo)
            ax.annotate(f"{val[best]:.3f}", (ep[best], val[best]), textcoords="offset points",
                        xytext=(0, 8 if above else -14), ha="center", color=INK2, fontsize=9)
        ax.set_title(title)
        ax.set_xlabel("epoka")
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        if key != "loss":
            ax.set_ylim(0, 1.05)
    axes[0].legend(loc="upper right")
    fig.suptitle("Przebieg treningu", x=0.01, ha="left", fontsize=14, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _draw_cm(ax, cm, title):
    labels = ["inne", "piła"]
    row = cm.sum(axis=1, keepdims=True)
    frac = cm / np.maximum(row, 1)
    ax.imshow(frac, cmap=SEQ_BLUE, vmin=0, vmax=1)
    names = [["TN", "FP"], ["FN", "TP"]]
    for i in range(2):
        for j in range(2):
            color = "#ffffff" if frac[i, j] > 0.55 else INK
            ax.text(j, i - 0.12, f"{cm[i, j]}", ha="center", va="center",
                    fontsize=18, fontweight="bold", color=color)
            ax.text(j, i + 0.18, f"{names[i][j]}  {100 * frac[i, j]:.1f}%",
                    ha="center", va="center", fontsize=9, color=color)
    ax.set_xticks([0, 1], labels)
    ax.set_yticks([0, 1], labels)
    ax.set_xlabel("predykcja")
    ax.set_ylabel("prawda")
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    tn, fp, fn, tp = cm.ravel()
    acc = (tp + tn) / max(cm.sum(), 1)
    prec, rec = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    ax.set_title(f"{title}\nacc {acc:.3f} · precision {prec:.3f} · recall {rec:.3f} · F1 {f1:.3f}",
                 fontsize=10)


def plot_confusion(results, y, thr, path):
    fig, axes = plt.subplots(1, len(results), figsize=(4.6 * len(results), 4.4))
    for ax, (name, p) in zip(np.atleast_1d(axes), results.items()):
        _draw_cm(ax, confusion(p, y, thr), name)
    fig.suptitle(f"Macierz pomyłek (próg {thr:.2f}, % w wierszu)", x=0.01, ha="left",
                 fontsize=14, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_roc_pr(results, y, thr, path):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.4))
    colors = [BLUE, ORANGE]
    for (name, p), color in zip(results.items(), colors):
        fpr, tpr, prec, auc, ap = roc_pr(p, y)
        a1.plot(fpr, tpr, color=color, label=f"{name}  AUC {auc:.3f}")
        a2.plot(tpr, prec, color=color, label=f"{name}  AP {ap:.3f}")
        cm = confusion(p, y, thr)
        tn, fp, fn, tp = cm.ravel()
        r, f = tp / max(tp + fn, 1), fp / max(fp + tn, 1)
        a1.scatter(f, r, s=50, color=color, edgecolor=SURFACE, linewidth=2, zorder=3)
        a2.scatter(r, tp / max(tp + fp, 1), s=50, color=color, edgecolor=SURFACE,
                   linewidth=2, zorder=3)
    a1.plot([0, 1], [0, 1], color=MUTED, linewidth=1, linestyle="--")
    a1.set(title="ROC", xlabel="odsetek fałszywych alarmów (FPR)", ylabel="recall (TPR)",
           xlim=(-0.01, 1.01), ylim=(-0.01, 1.03))
    a2.set(title="Precision-Recall", xlabel="recall", ylabel="precision",
           xlim=(-0.01, 1.01), ylim=(-0.01, 1.03))
    for ax in (a1, a2):
        ax.legend(loc="lower right")
    fig.text(0.01, -0.02, f"Kropka = punkt pracy przy progu {thr:.2f}", color=MUTED, fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_hist(p, y, thr, path, name):
    fig, ax = plt.subplots(figsize=(7, 3.8))
    bins = np.linspace(0, 1, 41)
    ax.hist(p[y == 0], bins=bins, color=BLUE, alpha=0.75, label=f"inne (n={int((y == 0).sum())})",
            edgecolor=SURFACE, linewidth=1)
    ax.hist(p[y == 1], bins=bins, color=ORANGE, alpha=0.75, label=f"piła (n={int((y == 1).sum())})",
            edgecolor=SURFACE, linewidth=1)
    ax.axvline(thr, color=INK2, linewidth=1.2, linestyle="--")
    ax.text(thr, 0.97, f" próg {thr:.2f}", color=INK2, va="top", fontsize=9,
            transform=ax.get_xaxis_transform())
    ax.set(title=f"Rozkład p(piła) na zbiorze testowym ({name})", xlabel="p(piła)",
           ylabel="liczba okien")
    ax.legend(loc="upper left", bbox_to_anchor=(0.12, 1))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_false_alarms(p, y, meta, thr, path, top=15, unit="okien"):
    pred = p >= thr
    fps, total = defaultdict(int), Counter()
    for pi, yi, m in zip(pred, y, meta):
        if yi == 0:
            for cat in {m["bed"], m["fg"]} - {None}:
                total[cat] += 1
                fps[cat] += int(pi)
    cats = sorted(total, key=lambda c: (fps[c] / total[c], total[c]), reverse=True)[:top][::-1]
    rate = np.array([100 * fps[c] / total[c] for c in cats])
    fig, ax = plt.subplots(figsize=(7, 0.32 * len(cats) + 1.4))
    bars = ax.barh(cats, rate, color=BLUE, height=0.7, edgecolor=SURFACE, linewidth=2)
    for b, c, r in zip(bars, cats, rate):
        ax.text(b.get_width() + 0.4, b.get_y() + b.get_height() / 2,
                f"{r:.1f}%  ({fps[c]}/{total[c]})", va="center", fontsize=8.5, color=INK2)
    ax.set_xlim(0, max(rate.max() * 1.35, 5) if len(rate) else 5)
    ax.grid(axis="y", visible=False)
    ax.set(title="Fałszywe alarmy wg dźwięku tła/zdarzenia", xlabel=f"% {unit} bez piły uznanych za piłę")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def save_all(out_dir):
    out = Path(out_dir)
    plots = out / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    thr = C.DETECT_THRESHOLD
    d = np.load(out / "eval.npz", allow_pickle=True)
    y, meta = d["y"], list(d["meta"])
    results = {"float32": d["p_float"], "int8": d["p_int8"]}

    hist_path = out / "history.json"
    if hist_path.exists():
        plot_history(json.loads(hist_path.read_text()), plots / "history.png")
    plot_confusion(results, y, thr, plots / "confusion_matrix.png")
    plot_roc_pr(results, y, thr, plots / "roc_pr.png")
    plot_hist(results["int8"], y, thr, plots / "score_hist.png", "int8")
    plot_false_alarms(results["int8"], y, meta, thr, plots / "false_alarms.png")
    print(f"Wykresy zapisane w {plots}/")


if __name__ == "__main__":
    save_all(sys.argv[1] if len(sys.argv) > 1 else "out")
