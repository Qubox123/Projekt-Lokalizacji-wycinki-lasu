"""Wspólne parametry przetwarzania dźwięku.

Te same wartości muszą być użyte w firmware ESP32 (train.py eksportuje je do
`out/feature_config.h`), inaczej model dostanie inny spektrogram niż przy treningu.
"""

SAMPLE_RATE = 16000          # Hz, typowe dla mikrofonów I2S (INMP441, ICS-43434)
WINDOW_SEC = 1.0             # długość okna klasyfikacji
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SEC)
STREAM_HOP_SEC = 0.5         # co ile klasyfikujemy w trybie strumieniowym

# Spektrogram
N_FFT = 512                  # 32 ms
HOP = 320                    # 20 ms
N_FRAMES = 1 + (WINDOW_SAMPLES - N_FFT) // HOP   # 49 ramek
N_MELS = 40
FMIN = 100.0
FMAX = 8000.0
LOG_EPS = 1e-6

# Filtr górnoprzepustowy: wycina dudnienie wiatru i niskie pasmo szumu drzew.
# Piła ma ton podstawowy ~90–250 Hz i silne harmoniczne do kilku kHz, więc 150 Hz
# niewiele z niej zabiera.
HIGHPASS_HZ = 150.0
HIGHPASS_ORDER = 2           # jeden biquad -> tanio na ESP32 (esp-dsp dsps_biquad_f32)

# Odejmowanie widmowe szumu tła (deszcz, wiatr, szum liści).
# P' = max(P - ALPHA * N, FLOOR * P), gdzie N to profil tła w pasmach mel.
SUBTRACT_ALPHA = 1.5         # nadodejmowanie, tłumi też fluktuacje szumu
SUBTRACT_FLOOR = 0.05        # maks. tłumienie ok. 13 dB, chroni przed "muzycznym szumem"

# Śledzenie profilu tła na urządzeniu (EMA aktualizowana tylko gdy nie ma piły)
NOISE_EMA = 0.1              # przy hopie 0.5 s stała czasowa ok. 5 s
NOISE_UPDATE_BELOW = 0.3     # aktualizuj profil tylko gdy p(piła) < tej wartości

# Decyzja
DETECT_THRESHOLD = 0.6
DETECT_K, DETECT_N = 2, 3    # alarm gdy K z ostatnich N okien > progu
