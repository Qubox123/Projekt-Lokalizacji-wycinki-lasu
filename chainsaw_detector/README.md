# Detektor piły mechanicznej na ESP32

Klasyfikator binarny **piła / inne** (deszcz, wiatr, szum drzew, ptaki, owady, silniki…)
działający na węźle w lesie. Wynik `p(piła)` uruchamia wysłanie obwiedni energii przez LoRa
do serwera lokalizacji.

## Potok

```
mikrofon I2S 16 kHz
  -> filtr górnoprzepustowy 150 Hz (1 biquad)   : wycina dudnienie wiatru / szum drzew
  -> okno 1 s, ramki 32 ms co 20 ms, FFT 512
  -> 40 pasm mel (100–8000 Hz)
  -> odejmowanie widmowe profilu tła             : tłumi stacjonarny deszcz, wiatr, szum liści
  -> log  ->  spektrogram 49 x 40
  -> DS-CNN int8 (~10 tys. parametrów, ~29 KB flash)
  -> p(piła); alarm gdy 2 z 3 kolejnych okien > 0.6
```

Profil tła to średnia EMA widma mel, **aktualizowana tylko gdy model nie słyszy piły**,
więc długa wycinka nie zostanie "nauczona" jako tło i odjęta.

## Trening

Każdy przykład jest syntetyzowany na bieżąco: 1 s tła z datasetu + piła albo inne zdarzenie
w losowym SNR (-5…20 dB), losowa głośność, filtr dolnoprzepustowy symulujący odległość,
SpecAugment. Profil szumu liczony jest z fragmentu tła *przed* oknem, tak jak na węźle.
Podział train/val/test jest po nagraniu źródłowym, więc nie ma przecieku.

```bash
pip install -r requirements.txt
```

Szybki test, czy wszystko działa (sztuczne dźwięki):

```bash
python train.py --synthetic --epochs 5
```

Prawdziwe dane:

```bash
python train.py --esc50 data/ESC-50-master --fsc22 data/FSC22 --cache out/clips.pkl
```

| Dataset | Skąd | Uwagi |
|---|---|---|
| ESC-50 | github.com/karolpiczak/ESC-50 | 40 klipów "chainsaw" + rain, wind, crickets, birds… |
| FSC22 | Kaggle, "FSC22 Forest Sound Classification" | Chainsaw + dźwięki lasu, trudne negatywy: Generator, VehicleEngine, Handsaw |
| własne | `--folder dir` | `dir/chainsaw/*.wav` = piła, każdy inny podfolder = tło |

Najwięcej poprawią **nagrania z docelowego lasu** (samo tło, kilka godzin) dodane przez `--folder`.

Test strumieniowy na pliku (dokładnie ta sama logika co na ESP32, model int8):

```bash
python infer.py nagranie.wav --model out/chainsaw_int8.tflite
```

## Wyniki w `out/`

- `chainsaw_int8.tflite`: model w pełni int8
- `chainsaw_model_data.h`: model jako tablica C dla TFLite Micro
- `feature_config.h`: parametry DSP, współczynniki biquada (format esp-dsp), rzadki bank filtrów mel,
  skala i zero point wejścia/wyjścia
- `chainsaw.keras`: model float (do dalszego treningu)

## ESP32 (do zrobienia w firmware)

- Biblioteki: `esp-tflite-micro` (z ESP-NN) i `esp-dsp` (`dsps_biquad_f32`, `dsps_fft2r_fc32`).
- Operacje do zarejestrowania w `MicroMutableOpResolver<7>`: Conv2D, DepthwiseConv2D, Mean,
  FullyConnected, Logistic, Mul, Sub.
- Wejście: `q = round(logmel / CS_INPUT_SCALE) + CS_INPUT_ZERO_POINT`, ograniczone do [-128, 127].
- Tensor arena: zacznij od 40 KB i zmniejsz według `interpreter.arena_used_bytes()`.
- Bufor audio na 1 s = 32 KB (int16). Klasyfikacja co 0.5 s.
- Zmiana czegokolwiek w `config.py` wymaga ponownego treningu.
