# Firmware detektora piły (XIAO ESP32-S3)

ESP-IDF + TFLite Micro (`espressif/esp-tflite-micro`). Logika jak `stream_detect()` w `infer.py`:
okna 1 s co 0,5 s, filtr HP 150 Hz, log-mel 49×40 z odejmowaniem profilu tła, sieć int8,
alarm gdy 2 z 3 okien ≥ progu (0,8). Przy alarmie zapala się dioda użytkownika (GPIO 21).

Model i parametry cech są brane z `../out_unified_v2/` (`chainsaw_model_data.h`, `feature_config.h`).
Po nowym treningu zmień `MODEL_DIR` w `src/CMakeLists.txt`.

## Mikrofon

| środowisko | mikrofon | piny |
|---|---|---|
| `inmp441` (domyślne) | INMP441 / ICS-43434 na I2S | SCK → D1 (GPIO 2), WS → D2 (GPIO 3), SD → D0 (GPIO 1), L/R → GND, VDD → 3V3 |
| `sense` | wbudowany PDM w XIAO ESP32-S3 Sense | CLK GPIO 42, DATA GPIO 41 |

Piny I2S nie kolidują z Wio-SX1262 (GPIO 7–9, 38–42). Inne piny: `build_flags = -DMIC_SCK=...`.

## Wgrywanie

```bash
cd chainsaw_detector/firmware
pio run -e inmp441 -t upload --upload-port /dev/ttyACM2
pio device monitor -p /dev/ttyACM2 -b 115200
```

Pierwsza kompilacja pobiera ESP-IDF i TFLite Micro (kilka minut).

## Co pokazuje konsola

```
=== Detektor piły, próg 0.80, alarm 2 z 3 ===
Model: 45688 B, arena: ... B
    0.0s  p=0.02  rms= -48.3 dBFS  cechy= 9 ms  sieć=30 ms
```

- `rms` to poziom okna. Model uczył się na poziomach od −65 do −10 dBFS. Cisza bliska −90 dBFS
  albo stałe ok. 0 dBFS oznacza zły odczyt mikrofonu (piny, L/R, format), a nie problem modelu.
- Pierwsze okno po starcie służy jako profil tła, więc start powinien być bez piły.

## Sprawdzenie zgodności z Pythonem

```bash
python firmware/tools/check_features.py nagranie.wav
```

Kompiluje `src/features.cpp` na PC i porównuje cechy i p(piła) z `features.py`.
