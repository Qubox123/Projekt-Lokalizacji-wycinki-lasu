// Szuka mikrofonu na pinach XIAO ESP32-S3 / ESP32-C6 bez fizycznego dostępu do płytki.
// Kolejno: wejścia analogowe (ADC), PDM (pary CLK/DATA), I2S (SCK/WS/SD, oba kanały).
// Prawdziwy dźwięk ma wyraźną korelację sąsiednich próbek (r1), pływający pin daje szum
// bez korelacji albo stałą wartość. Wynik wypisywany jest w kółko co 15 s.

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include <initializer_list>

#include "driver/gpio.h"
#include "driver/i2s_pdm.h"
#include "soc/soc_caps.h"
#include "driver/i2s_std.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

struct Pin { int gpio; const char* name; };
#if CONFIG_IDF_TARGET_ESP32C6
// XIAO ESP32-C6 (bez GPIO 3/14 - przełącznik anteny, 12/13 - USB, 8/9/15 - strapping)
static const Pin kPins[] = {{0, "D0"}, {1, "D1"}, {2, "D2"}, {21, "D3"}, {22, "D4"}, {23, "D5"},
                            {16, "D6"}, {17, "D7"}, {19, "D8"}, {20, "D9"}, {18, "D10"}};
static constexpr int kAdcMaxGpio = 6;              // ADC1: GPIO 0-6, kanał = numer GPIO
static int adc_channel(int g) { return g; }
#else
static const Pin kPins[] = {{1, "D0"}, {2, "D1"}, {3, "D2"}, {4, "D3"}, {5, "D4"}, {6, "D5"},
                            {43, "D6"}, {44, "D7"}, {7, "D8"}, {8, "D9"}, {9, "D10"}};
static constexpr int kAdcMaxGpio = 10;             // ADC1: GPIO 1-10, kanał = GPIO - 1
static int adc_channel(int g) { return g - 1; }
#endif
static constexpr int kNPins = sizeof(kPins) / sizeof(kPins[0]);

struct Hit { char what[64]; float rms_db, r1; };
static Hit g_hits[200];
static int g_nhits = 0;

struct Stats { float rms_db, r1, sat; };

static Stats stats(const float* x, int n) {
  double m = 0;
  for (int i = 0; i < n; i++) m += x[i];
  m /= n;
  double v = 0, c = 0;
  int sat = 0;
  for (int i = 0; i < n; i++) {
    double d = x[i] - m;
    v += d * d;
    if (i + 1 < n) c += d * (x[i + 1] - m);
    if (fabsf(x[i]) > 0.98f) sat++;
  }
  Stats s;
  s.rms_db = 10.0f * log10f((float)(v / n) + 1e-20f);
  s.r1 = v > 0 ? (float)(c / v) : 0.0f;
  s.sat = (float)sat / n;
  return s;
}

// Pin bez mikrofonu ma podciąganie do 3,3 V -> same jedynki (stała wartość) albo zera.
// Wszystko, co się zmienia i nie jest przesterowane, wypisujemy; w cichym pomieszczeniu
// szum własny mikrofonu ma małe r1, więc r1 tylko pomaga ocenić, nie odrzuca.
static bool looks_like_audio(const Stats& s) {
  return s.rms_db > -135.0f && s.sat < 0.05f;
}

static void record(const char* what, const Stats& s) {
  printf("  kandydat: %-40s rms=%6.1f dBFS r1=%.2f\n", what, s.rms_db, s.r1);
  if (g_nhits < 200) {
    Hit& h = g_hits[g_nhits++];
    snprintf(h.what, sizeof(h.what), "%s", what);
    h.rms_db = s.rms_db;
    h.r1 = s.r1;
  }
}

static float g_buf[4096];

static void scan_adc() {
  printf("\n--- ADC (mikrofon analogowy) ---\n");
  adc_oneshot_unit_handle_t adc;
  adc_oneshot_unit_init_cfg_t ucfg = {};
  ucfg.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&ucfg, &adc) != ESP_OK) return;
  for (int i = 0; i < kNPins; i++) {
    int g = kPins[i].gpio;
    if (g > kAdcMaxGpio) continue;
    adc_channel_t ch = (adc_channel_t)adc_channel(g);
    adc_oneshot_chan_cfg_t ccfg = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    adc_oneshot_config_channel(adc, ch, &ccfg);
    double mean = 0;
    for (int k = 0; k < 2048; k++) {
      int raw = 0;
      adc_oneshot_read(adc, ch, &raw);
      g_buf[k] = raw / 4095.0f;
      mean += raw;
    }
    mean /= 2048;
    Stats s = stats(g_buf, 2048);
    printf("  %-3s GPIO%-2d  średnio %4.0f mV  szum=%6.1f dB  r1=%.2f\n", kPins[i].name, g,
           mean * 3100.0 / 4095.0, s.rms_db, s.r1);
    // analogowy moduł: ok. 0,9-2 V składowej stałej i zmienny sygnał
    if (mean > 1100 && mean < 2700 && s.rms_db > -60 && s.r1 > 0.3f) {
      char w[64];
      snprintf(w, sizeof(w), "ANALOG %s (GPIO%d)", kPins[i].name, g);
      record(w, s);
    }
  }
  adc_oneshot_del_unit(adc);
  for (int i = 0; i < kNPins; i++) gpio_reset_pin((gpio_num_t)kPins[i].gpio);
}

// Odczyt stereo -> osobno lewy i prawy kanał.
template <typename T>
static bool read_stereo(i2s_chan_handle_t rx, float scale, int skip, int n, Stats* left,
                        Stats* right) {
  static T raw[2 * 512];
  static float l[2048], r[2048];
  int got_frames = 0, skipped = 0;
  while (got_frames < n) {
    size_t bytes = 0;
    if (i2s_channel_read(rx, raw, sizeof(raw), &bytes, pdMS_TO_TICKS(300)) != ESP_OK) return false;
    int frames = bytes / (2 * sizeof(T));
    for (int i = 0; i < frames; i++) {
      if (skipped < skip) { skipped++; continue; }
      if (got_frames >= n) break;
      l[got_frames] = raw[2 * i] * scale;
      r[got_frames] = raw[2 * i + 1] * scale;
      got_frames++;
    }
  }
  *left = stats(l, n);
  *right = stats(r, n);
  return true;
}

#if SOC_I2S_SUPPORTS_PDM_RX
static void try_pdm(int clk, int din, const char* cname, const char* dname) {
  i2s_chan_handle_t rx;
  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  if (i2s_new_channel(&chan, nullptr, &rx) != ESP_OK) return;
  i2s_pdm_rx_config_t cfg = {
      .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(16000),
      .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
      .gpio_cfg = {.clk = (gpio_num_t)clk, .din = (gpio_num_t)din, .invert_flags = {.clk_inv = false}},
  };
  Stats sl, sr;
  if (i2s_channel_init_pdm_rx_mode(rx, &cfg) == ESP_OK && i2s_channel_enable(rx) == ESP_OK) {
    if (read_stereo<int16_t>(rx, 1.0f / 32768.0f, 2048, 2048, &sl, &sr)) {
      char w[64];
      if (looks_like_audio(sl)) {
        snprintf(w, sizeof(w), "PDM CLK=%s DATA=%s kanał L", cname, dname);
        record(w, sl);
      }
      if (looks_like_audio(sr)) {
        snprintf(w, sizeof(w), "PDM CLK=%s DATA=%s kanał R", cname, dname);
        record(w, sr);
      }
    }
    i2s_channel_disable(rx);
  }
  i2s_del_channel(rx);
  gpio_reset_pin((gpio_num_t)clk);
  gpio_reset_pin((gpio_num_t)din);
}

#endif

static void scan_pdm() {
  printf("\n--- PDM ---\n");
#if !SOC_I2S_SUPPORTS_PDM_RX
  printf("  ten układ nie ma odbioru PDM, pomijam\n");
  return;
#endif
#if SOC_I2S_SUPPORTS_PDM_RX
#if CONFIG_IDF_TARGET_ESP32S3
  try_pdm(42, 41, "GPIO42", "GPIO41");             // wbudowany mikrofon XIAO Sense
#endif
  for (int a = 0; a < kNPins; a++)
    for (int b = 0; b < kNPins; b++)
      if (a != b) try_pdm(kPins[a].gpio, kPins[b].gpio, kPins[a].name, kPins[b].name);
#endif
}

static void scan_i2s() {
  printf("\n--- I2S (np. INMP441), %d kombinacji ---\n", kNPins * (kNPins - 1) * (kNPins - 2));
  int done = 0;
  for (int a = 0; a < kNPins; a++)
    for (int b = 0; b < kNPins; b++)
      for (int c = 0; c < kNPins; c++) {
        if (a == b || b == c || a == c) continue;
        if (++done % 100 == 0) printf("  ... %d\n", done);
        i2s_chan_handle_t rx;
        i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
        if (i2s_new_channel(&chan, nullptr, &rx) != ESP_OK) continue;
        i2s_std_config_t cfg = {
            .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000),
            .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
            .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = (gpio_num_t)kPins[a].gpio,
                         .ws = (gpio_num_t)kPins[b].gpio, .dout = I2S_GPIO_UNUSED,
                         .din = (gpio_num_t)kPins[c].gpio,
                         .invert_flags = {.mclk_inv = false, .bclk_inv = false, .ws_inv = false}},
        };
        Stats sl, sr;
        if (i2s_channel_init_std_mode(rx, &cfg) == ESP_OK && i2s_channel_enable(rx) == ESP_OK) {
          // INMP441 potrzebuje ok. 85 ms od startu zegara, stąd pominięte 2048 ramek (128 ms)
          if (read_stereo<int32_t>(rx, 1.0f / 2147483648.0f, 2048, 2048, &sl, &sr)) {
            char w[64];
            if (looks_like_audio(sl)) {
              snprintf(w, sizeof(w), "I2S SCK=%s WS=%s SD=%s kanał L", kPins[a].name,
                       kPins[b].name, kPins[c].name);
              record(w, sl);
            }
            if (looks_like_audio(sr)) {
              snprintf(w, sizeof(w), "I2S SCK=%s WS=%s SD=%s kanał R", kPins[a].name,
                       kPins[b].name, kPins[c].name);
              record(w, sr);
            }
          }
          i2s_channel_disable(rx);
        }
        i2s_del_channel(rx);
        for (int p : {a, b, c}) gpio_reset_pin((gpio_num_t)kPins[p].gpio);
      }
}

extern "C" void app_main() {
  esp_log_level_set("gpio", ESP_LOG_WARN);         // gpio_reset_pin loguje każdy pin
  vTaskDelay(pdMS_TO_TICKS(3000));                 // czas na otwarcie konsoli
  printf("\n=== Szukanie mikrofonu (ok. 5 min) ===\n");
  scan_adc();
  scan_pdm();
  scan_i2s();
  while (true) {
    printf("\n=== WYNIK: %d kandydatów (najlepsze mają najwyższe r1 i rms) ===\n", g_nhits);
    for (int i = 0; i < g_nhits; i++)
      printf("  %-40s rms=%6.1f dBFS r1=%.2f\n", g_hits[i].what, g_hits[i].rms_db, g_hits[i].r1);
    if (!g_nhits) printf("  nic nie znaleziono\n");
    vTaskDelay(pdMS_TO_TICKS(15000));
  }
}
