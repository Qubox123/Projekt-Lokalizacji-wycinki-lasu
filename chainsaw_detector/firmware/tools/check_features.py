"""Sprawdza na PC, że cechy z firmware (src/features.cpp) są takie same jak w features.py.

Kompiluje features.cpp natywnie, przepuszcza to samo nagranie przez obie wersje
(strumieniowo, jak infer.stream_detect) i porównuje cechy oraz p(piła) z modelu int8.

    python firmware/tools/check_features.py nagranie.wav [--model-dir out_unified_v2]
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import config as C          # noqa: E402
import datasets as D        # noqa: E402
import features as F        # noqa: E402
from export import TFLiteClassifier  # noqa: E402

# Strumień jak w main.cpp, ale p(piła) czytane z pliku policzonego w Pythonie,
# żeby profil tła aktualizował się identycznie w obu wersjach.
HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "features.h"
int main(int argc, char** argv) {
  FILE* fa = fopen(argv[1], "rb"); FILE* fp = fopen(argv[2], "rb"); FILE* fo = fopen(argv[3], "wb");
  static float win[CS_WINDOW_SAMPLES], hop[CS_STREAM_HOP], mel[CS_N_FRAMES * CS_N_MELS], feat[CS_N_FRAMES * CS_N_MELS];
  Highpass hp; NoiseTracker tr; long filled = 0; float p;
  while (fread(hop, sizeof(float), CS_STREAM_HOP, fa) == CS_STREAM_HOP) {
    hp.process(hop, hop, CS_STREAM_HOP);
    memmove(win, win + CS_STREAM_HOP, (CS_WINDOW_SAMPLES - CS_STREAM_HOP) * sizeof(float));
    memcpy(win + CS_WINDOW_SAMPLES - CS_STREAM_HOP, hop, CS_STREAM_HOP * sizeof(float));
    filled += CS_STREAM_HOP;
    if (filled < CS_WINDOW_SAMPLES) continue;
    mel_power_slide(win, mel, tr.ready());
    if (!tr.ready()) tr.update(mel, 0.0f);
    log_mel(mel, tr.profile(), feat);
    fwrite(feat, sizeof(float), CS_N_FRAMES * CS_N_MELS, fo);
    if (fread(&p, sizeof(float), 1, fp) != 1) break;
    tr.update(mel, p);
  }
  fclose(fo);
  return 0;
}
"""


def python_stream(x, clf):
    """Kopia infer.stream_detect, która zwraca też cechy."""
    xf = F.highpass(x)
    hop = int(C.STREAM_HOP_SEC * C.SAMPLE_RATE)
    tracker, feats, ps = F.NoiseTracker(), [], []
    for start in range(0, len(xf) - C.WINDOW_SAMPLES + 1, hop):
        mel = F.mel_power(xf[start:start + C.WINDOW_SAMPLES])
        if tracker.profile is None:
            tracker.update(mel, 0.0)
        feat = F.log_mel(mel, tracker.profile)
        p = float(clf(feat)[0])
        tracker.update(mel, p)
        feats.append(feat)
        ps.append(p)
    return np.array(feats), np.array(ps, np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--model-dir", default=str(ROOT / "out_unified_v2"))
    args = ap.parse_args()
    model_dir = Path(args.model_dir)

    clf = TFLiteClassifier(str(model_dir / "chainsaw_int8.tflite"))
    x = D.load_audio(args.wav)
    hop = int(C.STREAM_HOP_SEC * C.SAMPLE_RATE)
    x = x[:len(x) // hop * hop]
    feats_py, p_py = python_stream(x, clf)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "harness.cpp").write_text(HARNESS)
        exe = tmp / "harness"
        subprocess.run(["c++", "-std=c++17", "-O2", f"-I{HERE.parent / 'src'}", f"-I{model_dir}",
                        str(tmp / "harness.cpp"), str(HERE.parent / "src" / "features.cpp"),
                        "-o", str(exe)], check=True)
        x.astype("<f4").tofile(tmp / "audio.f32")
        p_py.astype("<f4").tofile(tmp / "p.f32")
        subprocess.run([str(exe), tmp / "audio.f32", tmp / "p.f32", tmp / "feat.f32"], check=True)
        feats_c = np.fromfile(tmp / "feat.f32", "<f4").reshape(-1, C.N_FRAMES, C.N_MELS)

    p_c = np.array([float(clf(f)[0]) for f in feats_c])
    n = min(len(p_c), len(p_py))
    diff = np.abs(feats_c[:n] - feats_py[:n])
    print(f"okien: {n}  |cechy C - Python|: średnio {diff.mean():.2e}, maks. {diff.max():.2e}")
    print(f"|p C - p Python|: maks. {np.abs(p_c[:n] - p_py[:n]).max():.3f}")
    ok = np.abs(p_c[:n] - p_py[:n]).max() <= 2 * 3.90625e-3
    print("OK" if ok else "RÓŻNICA - sprawdź features.cpp")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
