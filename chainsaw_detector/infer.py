"""Detekcja strumieniowa na pliku audio - symulacja tego, co robi węzeł ESP32.

    python infer.py nagranie.wav --model out/chainsaw_int8.tflite
"""

import argparse
from collections import deque

import numpy as np

import config as C
import datasets as D
import features as F
from export import TFLiteClassifier


def stream_detect(audio, clf):
    """Okna 1 s co 0.5 s, profil tła śledzony tylko gdy brak piły, decyzja K z N."""
    x = F.highpass(audio)            # filtr działa ciągle, jak na urządzeniu
    hop = int(C.STREAM_HOP_SEC * C.SAMPLE_RATE)
    tracker, recent, events = F.NoiseTracker(), deque(maxlen=C.DETECT_N), []
    for start in range(0, len(x) - C.WINDOW_SAMPLES + 1, hop):
        mel = F.mel_power(x[start:start + C.WINDOW_SAMPLES])
        if tracker.profile is None:
            tracker.update(mel, 0.0)   # pierwsze okno = kalibracja tła
        p = float(clf(F.log_mel(mel, tracker.profile))[0])
        tracker.update(mel, p)
        recent.append(p >= C.DETECT_THRESHOLD)
        alarm = sum(recent) >= C.DETECT_K
        events.append((start / C.SAMPLE_RATE, p, alarm))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--model", default="out/chainsaw_int8.tflite")
    args = ap.parse_args()

    clf = TFLiteClassifier(args.model)
    for t, p, alarm in stream_detect(D.load_audio(args.wav), clf):
        bar = "#" * int(p * 30)
        print(f"{t:7.1f}s  p={p:.2f}  {bar:30s} {'PIŁA!' if alarm else ''}")


if __name__ == "__main__":
    main()
