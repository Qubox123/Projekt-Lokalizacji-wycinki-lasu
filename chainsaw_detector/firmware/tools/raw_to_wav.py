"""Zamienia strumień z rejestratora (recorder/, pakiety binarne z ADC 32 kHz) na WAV 16 kHz.

    python firmware/tools/raw_to_wav.py pila_1m.raw [pila_3m.raw ...]

Dla każdego pliku zapisuje obok plik .wav (mono, 16 kHz, float, składowa stała usunięta,
skala jak raw_dbfs w programie na płytce: (raw - średnia) / 2048) i wypisuje statystyki:
długość, zmierzoną częstotliwość próbkowania, zgubione pakiety, poziom w dBFS i przesterowanie.
"""

import struct
import sys
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

MAGIC = bytes([0xA5, 0x5A, 0xC3, 0x3C])
HEADER = struct.Struct("<4sHHHHI")
N = 512
OUT_RATE = 16000


def parse(data):
    packets, pos, skipped = [], 0, 0
    size = HEADER.size + 2 * N
    while True:
        i = data.find(MAGIC, pos)
        if i < 0 or i + size > len(data):
            break
        _, seq, n, ch, _, t = HEADER.unpack_from(data, i)
        if n != N or ch > 6:
            skipped += 1
            pos = i + 1
            continue
        samples = np.frombuffer(data, "<u2", N, i + HEADER.size)
        packets.append((seq, ch, t, samples))
        pos = i + size
    return packets


def convert(path):
    path = Path(path)
    packets = parse(path.read_bytes())
    if len(packets) < 10:
        print(f"{path.name}: za mało danych ({len(packets)} pakietów) - czy płytka nagrywała?")
        return
    seqs = np.array([p[0] for p in packets], np.int64)
    gaps = (np.diff(seqs) % 65536) - 1
    # na początku bywają stare pakiety z bufora portu - odcinamy wszystko do ostatniej dziury
    # w pierwszych 10% nagrania; dziury dalej to prawdziwe zgubione dane
    breaks = np.where(gaps != 0)[0]
    early = breaks[breaks < len(packets) // 10]
    start = early[-1] + 1 if len(early) else 0
    packets = packets[start:]
    later = gaps[start:]
    lost = int(later[later > 0].sum())
    n_breaks = int((later != 0).sum())
    t = np.array([p[2] for p in packets], np.float64)
    dt = np.diff(t) % 2**32
    rate = N / np.median(dt) * 1e6
    raw = np.concatenate([p[3] for p in packets]).astype(np.float32)

    clip = float(np.mean((raw <= 0) | (raw >= 4095)))
    x = (raw - raw.mean()) / 2048.0
    # 32 kHz -> 16 kHz z filtrem antyaliasingowym, z poprawką na rzeczywistą częstotliwość ADC
    num, den = OUT_RATE, int(round(rate))
    g = gcd(num, den)
    y = resample_poly(x, num // g, den // g).astype(np.float32)
    out = path.with_suffix(".wav")
    sf.write(out, y, OUT_RATE, subtype="FLOAT")
    db = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)
    print(f"{path.name}: {len(y) / OUT_RATE:6.1f} s  ADC {rate:7.0f} Hz  kanał ch{packets[0][1]}  "
          f"średnio {raw.mean():6.0f}  poziom {db:6.1f} dBFS  przester {clip:.1%}  "
          f"zgubione pakiety {lost} ({n_breaks} przerw)  -> {out.name}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        convert(p)


if __name__ == "__main__":
    main()
