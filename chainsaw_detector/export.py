"""Kwantyzacja int8 do TFLite i eksport nagłówków C dla ESP32."""

from pathlib import Path

import numpy as np
import tensorflow as tf

import config as C
import features as F


def to_tflite_int8(model, representative):
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = lambda: ([x[None].astype(np.float32)] for x in representative)
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    return conv.convert()


class TFLiteClassifier:
    """Wrapper na model int8 - liczy dokładnie to, co policzy ESP32."""

    def __init__(self, path_or_bytes):
        kw = {"model_content": path_or_bytes} if isinstance(path_or_bytes, bytes) \
            else {"model_path": str(path_or_bytes)}
        self.it = tf.lite.Interpreter(**kw)
        self.it.allocate_tensors()
        self.inp = self.it.get_input_details()[0]
        self.out = self.it.get_output_details()[0]
        self.in_scale, self.in_zp = self.inp["quantization"]
        self.out_scale, self.out_zp = self.out["quantization"]

    def __call__(self, feats):
        """feats: (N_FRAMES, N_MELS) albo (B, N_FRAMES, N_MELS, 1) -> p(piła)."""
        feats = np.asarray(feats, np.float32).reshape(-1, C.N_FRAMES, C.N_MELS, 1)
        probs = []
        for x in feats:
            q = np.clip(np.round(x / self.in_scale + self.in_zp), -128, 127).astype(np.int8)
            self.it.set_tensor(self.inp["index"], q[None])
            self.it.invoke()
            y = self.it.get_tensor(self.out["index"])[0, 0]
            probs.append((float(y) - self.out_zp) * self.out_scale)
        return np.array(probs, np.float32)


def write_model_header(tflite_bytes, path, name="g_chainsaw_model"):
    body = ",\n".join(
        "  " + ", ".join(f"0x{b:02x}" for b in tflite_bytes[i:i + 12])
        for i in range(0, len(tflite_bytes), 12))
    Path(path).write_text(
        "// Wygenerowane przez train.py - nie edytować ręcznie.\n"
        "// Dołączać tylko w jednym pliku .cpp.\n"
        "#pragma once\n#include <stdint.h>\n\n"
        f"alignas(16) const unsigned char {name}[] = {{\n{body}\n}};\n"
        f"const unsigned int {name}_len = {len(tflite_bytes)};\n")


def _c_floats(values, per_line=8):
    vals = [f"{v:.8e}f" for v in np.asarray(values, np.float64).ravel()]
    return ",\n".join("  " + ", ".join(vals[i:i + per_line]) for i in range(0, len(vals), per_line))


def write_feature_header(path, clf: TFLiteClassifier):
    """Parametry przetwarzania + bank filtrów mel (rzadki) + filtr HP + kwantyzacja."""
    starts, lens, weights = [], [], []
    for row in F.MEL_FB:
        nz = np.nonzero(row)[0]
        starts.append(int(nz[0]))
        lens.append(int(nz[-1] - nz[0] + 1))
        weights.extend(row[nz[0]:nz[-1] + 1])
    offsets = np.concatenate([[0], np.cumsum(lens)[:-1]]).astype(int)
    sos = F.HP_SOS
    assert sos.shape[0] == 1, "nagłówek obsługuje jeden biquad (HIGHPASS_ORDER = 2)"
    b0, b1, b2, _, a1, a2 = sos[0]

    Path(path).write_text(f"""// Wygenerowane przez train.py - musi się zgadzać z config.py.
#pragma once
#include <stdint.h>

#define CS_SAMPLE_RATE      {C.SAMPLE_RATE}
#define CS_WINDOW_SAMPLES   {C.WINDOW_SAMPLES}
#define CS_STREAM_HOP       {int(C.STREAM_HOP_SEC * C.SAMPLE_RATE)}
#define CS_N_FFT            {C.N_FFT}
#define CS_HOP              {C.HOP}
#define CS_N_FRAMES         {C.N_FRAMES}
#define CS_N_MELS           {C.N_MELS}
#define CS_LOG_EPS          {C.LOG_EPS:e}f

// Odejmowanie szumu: P' = max(P - ALPHA*N, FLOOR*P)
#define CS_SUBTRACT_ALPHA   {C.SUBTRACT_ALPHA}f
#define CS_SUBTRACT_FLOOR   {C.SUBTRACT_FLOOR}f
#define CS_NOISE_EMA        {C.NOISE_EMA}f
#define CS_NOISE_UPDATE_BELOW {C.NOISE_UPDATE_BELOW}f

#define CS_DETECT_THRESHOLD {C.DETECT_THRESHOLD}f
#define CS_DETECT_K         {C.DETECT_K}
#define CS_DETECT_N         {C.DETECT_N}

// Kwantyzacja wejścia/wyjścia modelu int8
#define CS_INPUT_SCALE      {clf.in_scale:.8e}f
#define CS_INPUT_ZERO_POINT {clf.in_zp}
#define CS_OUTPUT_SCALE     {clf.out_scale:.8e}f
#define CS_OUTPUT_ZERO_POINT {clf.out_zp}

// Filtr górnoprzepustowy {C.HIGHPASS_HZ:.0f} Hz, format esp-dsp dsps_biquad_f32: b0, b1, b2, a1, a2
static const float cs_highpass_coef[5] = {{ {b0:.10e}f, {b1:.10e}f, {b2:.10e}f, {a1:.10e}f, {a2:.10e}f }};

// Okno Hanna (periodyczne): w[n] = 0.5 - 0.5*cos(2*pi*n/N_FFT)
// Moc: |X[k]|^2 / N_FFT, k = 0..N_FFT/2

// Bank filtrów mel w formie rzadkiej:
// mel[m] = sum_{{j<len[m]}} power[start[m]+j] * weights[offset[m]+j]
static const uint16_t cs_mel_start[CS_N_MELS] = {{ {", ".join(map(str, starts))} }};
static const uint16_t cs_mel_len[CS_N_MELS] = {{ {", ".join(map(str, lens))} }};
static const uint16_t cs_mel_offset[CS_N_MELS] = {{ {", ".join(map(str, offsets))} }};
static const float cs_mel_weights[{len(weights)}] = {{
{_c_floats(weights)}
}};
""")
