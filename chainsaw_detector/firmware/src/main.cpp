// Węzeł detektora piły: mikrofon -> cechy log-mel -> sieć int8 (TFLite Micro) -> alarm K z N.
// Ta sama logika co stream_detect() w infer.py: okna 1 s co 0,5 s, profil tła z pierwszego okna,
// aktualizowany tylko gdy p(piła) < CS_NOISE_UPDATE_BELOW.

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "audio_in.h"
#include "chainsaw_model_data.h"
#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "feature_config.h"
#include "features.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "node_config.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/schema/schema_generated.h"

static float g_window[CS_WINDOW_SAMPLES];     // ostatnia 1 s po filtrze HP
static float g_hop[CS_STREAM_HOP];
static float g_mel[CS_N_FRAMES * CS_N_MELS];
static float g_feat[CS_N_FRAMES * CS_N_MELS];

static tflite::MicroInterpreter* setup_model() {
  const tflite::Model* model = tflite::GetModel(g_chainsaw_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    printf("Zła wersja schematu modelu: %lu\n", (unsigned long)model->version());
    return nullptr;
  }
  // Operacje z out_unified_v2/chainsaw_int8.tflite
  static tflite::MicroMutableOpResolver<7> ops;
  ops.AddConv2D();
  ops.AddDepthwiseConv2D();
  ops.AddMean();
  ops.AddFullyConnected();
  ops.AddLogistic();
  ops.AddMul();
  ops.AddSub();

  auto* arena = (uint8_t*)heap_caps_aligned_alloc(16, TENSOR_ARENA_BYTES,
                                                  MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  static tflite::MicroInterpreter interp(model, ops, arena, TENSOR_ARENA_BYTES);
  if (interp.AllocateTensors() != kTfLiteOk) {
    printf("AllocateTensors nie powiodło się, zwiększ TENSOR_ARENA_BYTES\n");
    return nullptr;
  }
  printf("Model: %u B, arena: %u / %u B\n", g_chainsaw_model_len,
         (unsigned)interp.arena_used_bytes(), (unsigned)TENSOR_ARENA_BYTES);
  return &interp;
}

static float classify(tflite::MicroInterpreter* interp, const float* feat) {
  int8_t* in = interp->input(0)->data.int8;
  for (int i = 0; i < CS_N_FRAMES * CS_N_MELS; i++) {
    int q = (int)lroundf(feat[i] / CS_INPUT_SCALE) + CS_INPUT_ZERO_POINT;
    in[i] = (int8_t)(q < -128 ? -128 : q > 127 ? 127 : q);
  }
  if (interp->Invoke() != kTfLiteOk) return -1.0f;
  return (interp->output(0)->data.int8[0] - CS_OUTPUT_ZERO_POINT) * CS_OUTPUT_SCALE;
}

static float rms_dbfs(const float* x, int n) {
  double acc = 0.0;
  for (int i = 0; i < n; i++) acc += (double)x[i] * x[i];
  return 10.0f * log10f((float)(acc / n) + 1e-12f);
}

extern "C" void app_main() {
  if (LED_GPIO >= 0) {
    gpio_reset_pin((gpio_num_t)LED_GPIO);
    gpio_set_direction((gpio_num_t)LED_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level((gpio_num_t)LED_GPIO, 1);
  }

  printf("\n=== Detektor piły, próg %.2f, alarm %d z %d ===\n", DETECT_THRESHOLD,
         CS_DETECT_K, CS_DETECT_N);
  tflite::MicroInterpreter* interp = setup_model();
  if (!interp) {
    while (true) vTaskDelay(portMAX_DELAY);
  }
  audio_init();

  Highpass hp;
  NoiseTracker tracker;
  bool recent[CS_DETECT_N] = {};
  int64_t filled = 0;
  int n_windows = 0;

  while (true) {
    audio_read(g_hop, CS_STREAM_HOP);
    hp.process(g_hop, g_hop, CS_STREAM_HOP);
    memmove(g_window, g_window + CS_STREAM_HOP,
            (CS_WINDOW_SAMPLES - CS_STREAM_HOP) * sizeof(float));
    memcpy(g_window + CS_WINDOW_SAMPLES - CS_STREAM_HOP, g_hop, CS_STREAM_HOP * sizeof(float));
    filled += CS_STREAM_HOP;
    if (filled < CS_WINDOW_SAMPLES) continue;

    int64_t t0 = esp_timer_get_time();
    mel_power_slide(g_window, g_mel, tracker.ready());
    if (!tracker.ready()) tracker.update(g_mel, 0.0f);  // pierwsze okno = kalibracja tła
    log_mel(g_mel, tracker.profile(), g_feat);
    int64_t t1 = esp_timer_get_time();
    float p = classify(interp, g_feat);
    int64_t t2 = esp_timer_get_time();
    tracker.update(g_mel, p);

    recent[n_windows % CS_DETECT_N] = p >= DETECT_THRESHOLD;
    int hits = 0;
    for (bool r : recent) hits += r;
    bool alarm = hits >= CS_DETECT_K;
    if (LED_GPIO >= 0) gpio_set_level((gpio_num_t)LED_GPIO, alarm ? 0 : 1);

    float t = (float)(filled - CS_WINDOW_SAMPLES) / CS_SAMPLE_RATE;
    printf("%7.1fs  p=%.2f  rms=%6.1f dBFS  cechy=%2d ms  sieć=%2d ms%s\n", t, p,
           rms_dbfs(g_window, CS_WINDOW_SAMPLES), (int)((t1 - t0) / 1000),
           (int)((t2 - t1) / 1000), alarm ? "  PIŁA!" : "");
    n_windows++;
  }
}
