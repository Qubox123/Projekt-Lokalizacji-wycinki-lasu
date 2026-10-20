"""Ekstrakcja cech: filtr HP -> log-mel spektrogram z odejmowaniem szumu tła.

Wszystko jest celowo proste (biquad, FFT, mnożenie przez bank filtrów, log),
żeby dało się to 1:1 przepisać w C na ESP32 z użyciem esp-dsp.
"""

import numpy as np
from scipy import signal

import config as C


def hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)


def mel_to_hz(m):
    return 700.0 * (10.0 ** (np.asarray(m) / 2595.0) - 1.0)


def mel_filterbank(sr=C.SAMPLE_RATE, n_fft=C.N_FFT, n_mels=C.N_MELS,
                   fmin=C.FMIN, fmax=C.FMAX):
    """Trójkątny bank filtrów mel, kształt (n_mels, n_fft // 2 + 1)."""
    freqs = np.linspace(0.0, sr / 2.0, n_fft // 2 + 1)
    edges = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))
    fb = np.zeros((n_mels, freqs.size), np.float32)
    for i in range(n_mels):
        lo, mid, hi = edges[i:i + 3]
        up = (freqs - lo) / (mid - lo)
        down = (hi - freqs) / (hi - mid)
        fb[i] = np.maximum(0.0, np.minimum(up, down))
    assert (fb.sum(axis=1) > 0).all(), "pusty filtr mel - zmniejsz N_MELS albo zwiększ N_FFT"
    return fb


MEL_FB = mel_filterbank()
WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(C.N_FFT) / C.N_FFT)).astype(np.float32)
HP_SOS = signal.butter(C.HIGHPASS_ORDER, C.HIGHPASS_HZ, btype="highpass",
                       fs=C.SAMPLE_RATE, output="sos")


def highpass(x):
    return signal.sosfilt(HP_SOS, x).astype(np.float32)


def mel_power(x_filtered):
    """Moc w pasmach mel dla każdej ramki, kształt (frames, N_MELS)."""
    frames = np.lib.stride_tricks.sliding_window_view(x_filtered, C.N_FFT)[::C.HOP]
    spec = np.fft.rfft(frames * WINDOW, axis=-1)
    power = (spec.real ** 2 + spec.imag ** 2) / C.N_FFT
    return (power @ MEL_FB.T).astype(np.float32)


def noise_profile(x):
    """Średni profil tła w pasmach mel z fragmentu bez piły."""
    return mel_power(highpass(x)).mean(axis=0)


def subtract_noise(mel, profile):
    """Odejmowanie widmowe: usuwa stacjonarną część deszczu/wiatru/szumu liści."""
    if profile is None:
        return mel
    return np.maximum(mel - C.SUBTRACT_ALPHA * profile, C.SUBTRACT_FLOOR * mel)


def log_mel(mel, profile=None):
    return np.log(subtract_noise(mel, profile) + C.LOG_EPS).astype(np.float32)


def extract_features(window, profile=None):
    """Okno audio (WINDOW_SAMPLES,) w zakresie [-1, 1] -> (N_FRAMES, N_MELS)."""
    assert window.shape[0] == C.WINDOW_SAMPLES, window.shape
    return log_mel(mel_power(highpass(window)), profile)


class NoiseTracker:
    """Profil tła liczony na bieżąco, tak jak na węźle.

    Aktualizowany tylko wtedy, gdy model nie widzi piły, żeby długa wycinka
    nie została "wyuczona" jako tło i odjęta.
    """

    def __init__(self, ema=C.NOISE_EMA):
        self.ema = ema
        self.profile = None

    def update(self, mel_window, p_chainsaw):
        current = mel_window.mean(axis=0)
        if self.profile is None:
            self.profile = current
        elif p_chainsaw < C.NOISE_UPDATE_BELOW:
            self.profile = (1 - self.ema) * self.profile + self.ema * current
