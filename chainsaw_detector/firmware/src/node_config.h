// Ustawienia węzła. Każdą wartość można nadpisać w platformio.ini (build_flags = -DNAZWA=...).
#pragma once

// Mikrofon: domyślnie INMP441 na I2S. -DMIC_PDM = wbudowany mikrofon XIAO ESP32-S3 Sense.
// Piny I2S wybrane tak, żeby nie kolidowały z Wio-SX1262 (GPIO 7-9, 38-42).
#ifndef MIC_SCK
#define MIC_SCK 2        // XIAO D1
#endif
#ifndef MIC_WS
#define MIC_WS 3         // XIAO D2
#endif
#ifndef MIC_SD
#define MIC_SD 1         // XIAO D0
#endif
#ifndef MIC_PDM_CLK
#define MIC_PDM_CLK 42
#endif
#ifndef MIC_PDM_DATA
#define MIC_PDM_DATA 41
#endif

// Stałe wzmocnienie cyfrowe. Model uczył się na poziomach od -65 do -10 dBFS,
// więc bez AGC i bez normalizacji; zmieniać tylko, jeśli RMS tła w logach jest poza tym zakresem.
#ifndef MIC_GAIN
#define MIC_GAIN 1.0f
#endif

// Próg p(piła). W feature_config.h jest 0,6 z treningu; ewaluacja na surowych
// nagraniach (out_unified_v2) wskazała 0,8 jako lepszy kompromis.
#ifndef DETECT_THRESHOLD
#define DETECT_THRESHOLD CS_DETECT_THRESHOLD
#endif

// Dioda użytkownika XIAO ESP32-S3 (świeci przy stanie niskim), zapala się przy alarmie; -1 = brak.
#ifndef LED_GPIO
#define LED_GPIO 21
#endif

// Pamięć robocza TFLite Micro; faktyczne zużycie jest wypisywane przy starcie.
#ifndef TENSOR_ARENA_BYTES
#define TENSOR_ARENA_BYTES (100 * 1024)
#endif
