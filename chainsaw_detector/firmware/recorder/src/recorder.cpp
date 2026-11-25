// Rejestrator mikrofonu analogowego dla ESP32-C6 (ADC1, kanał = numer GPIO 0-6).
//
// Po starcie co 2 s wypisuje tekstem statystyki wszystkich kanałów ADC (tryb skanu),
// żeby było widać, na którym GPIO wisi mikrofon. Komendy z hosta (linia zakończona \n):
//   R     - nagrywaj z kanału wybranego automatycznie (napięcie ok. połowy zakresu, największy szum)
//   R<n>  - nagrywaj z kanału n (0-6)
//   S     - zatrzymaj nagrywanie i wróć do skanu
// Podczas nagrywania płytka wysyła wyłącznie pakiety binarne (bez tekstu):
//   magic A5 5A C3 3C | u16 seq | u16 n=512 | u16 kanał | u16 0 | u32 czas_us | n x u16 surowe 0-4095
// Próbkowanie 32 kHz, jak w programie z ADC, który był wcześniej na płytce.

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "driver/usb_serial_jtag.h"
#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static constexpr int kSampleHz = 32000;
static constexpr int kMaxChannel = 6;
static constexpr int kPacketSamples = 512;

static volatile int g_cmd_channel = -2;   // -2: brak komendy, -1: auto, 0-6: kanał, -3: stop
static int g_auto_channel = -1;

struct __attribute__((packed)) PacketHeader {
  uint8_t magic[4];
  uint16_t seq, n, channel, reserved;
  uint32_t time_us;
};

static void command_task(void*) {
  char line[16];
  int len = 0;
  while (true) {
    uint8_t c;
    if (usb_serial_jtag_read_bytes(&c, 1, portMAX_DELAY) != 1) continue;
    if (c != '\n' && c != '\r') {
      if (len < (int)sizeof(line) - 1) line[len++] = (char)c;
      continue;
    }
    line[len] = 0;
    len = 0;
    if (line[0] == 'R' || line[0] == 'r') {
      int ch = -1;
      if (line[1] >= '0' && line[1] <= '0' + kMaxChannel) ch = line[1] - '0';
      g_cmd_channel = ch;
    } else if (line[0] == 'S' || line[0] == 's') {
      g_cmd_channel = -3;
    }
  }
}

// Jeden przebieg skanu: średnia i odchylenie surowych odczytów na każdym kanale.
static void scan_once() {
  adc_oneshot_unit_handle_t adc;
  adc_oneshot_unit_init_cfg_t ucfg = {};
  ucfg.unit_id = ADC_UNIT_1;
  if (adc_oneshot_new_unit(&ucfg, &adc) != ESP_OK) return;
  float best = -1.0f;
  int best_ch = -1;
  printf("SKAN");
  for (int ch = 0; ch <= kMaxChannel; ch++) {
    adc_oneshot_chan_cfg_t ccfg = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    adc_oneshot_config_channel(adc, (adc_channel_t)ch, &ccfg);
    double sum = 0, sum2 = 0;
    const int n = 1024;
    for (int k = 0; k < n; k++) {
      int raw = 0;
      adc_oneshot_read(adc, (adc_channel_t)ch, &raw);
      sum += raw;
      sum2 += (double)raw * raw;
    }
    float mean = sum / n;
    float sd = sqrtf(fmaxf(0.0f, (float)(sum2 / n - (sum / n) * (sum / n))));
    printf("  ch%d mean=%4.0f sd=%5.1f", ch, mean, sd);
    // moduł analogowy (np. MAX9814) ma składową stałą ok. połowy zasilania
    if (mean > 800 && mean < 3300 && sd > best) {
      best = sd;
      best_ch = ch;
    }
  }
  adc_oneshot_del_unit(adc);
  g_auto_channel = best_ch;
  printf("  | auto=ch%d\n", best_ch);
}

static void record(int ch) {
  adc_continuous_handle_t h = nullptr;
  adc_continuous_handle_cfg_t hcfg = {};
  hcfg.max_store_buf_size = 16384;
  hcfg.conv_frame_size = kPacketSamples * SOC_ADC_DIGI_RESULT_BYTES;
  ESP_ERROR_CHECK(adc_continuous_new_handle(&hcfg, &h));

  adc_digi_pattern_config_t pattern = {};
  pattern.atten = ADC_ATTEN_DB_12;
  pattern.channel = (uint8_t)ch;
  pattern.unit = ADC_UNIT_1;
  pattern.bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
  adc_continuous_config_t cfg = {};
  cfg.pattern_num = 1;
  cfg.adc_pattern = &pattern;
  cfg.sample_freq_hz = kSampleHz;
  cfg.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  cfg.format = ADC_DIGI_OUTPUT_FORMAT_TYPE2;
  ESP_ERROR_CHECK(adc_continuous_config(h, &cfg));

  printf("NAGRYWAM ch%d %d Hz\n", ch, kSampleHz);
  fflush(stdout);
  vTaskDelay(pdMS_TO_TICKS(50));
  esp_log_level_set("*", ESP_LOG_NONE);   // od teraz w strumieniu tylko pakiety
  ESP_ERROR_CHECK(adc_continuous_start(h));

  static uint8_t raw[kPacketSamples * SOC_ADC_DIGI_RESULT_BYTES];
  static uint8_t packet[sizeof(PacketHeader) + kPacketSamples * 2];
  auto* hdr = (PacketHeader*)packet;
  auto* samples = (uint16_t*)(packet + sizeof(PacketHeader));
  const uint8_t magic[4] = {0xA5, 0x5A, 0xC3, 0x3C};
  memcpy(hdr->magic, magic, 4);
  hdr->n = kPacketSamples;
  hdr->channel = (uint16_t)ch;
  hdr->reserved = 0;
  uint16_t seq = 0;
  int filled = 0;

  while (g_cmd_channel == -2) {
    uint32_t got = 0;
    if (adc_continuous_read(h, raw, sizeof(raw), &got, 1000) != ESP_OK) continue;
    for (uint32_t i = 0; i + SOC_ADC_DIGI_RESULT_BYTES <= got; i += SOC_ADC_DIGI_RESULT_BYTES) {
      auto* r = (adc_digi_output_data_t*)&raw[i];
      if (r->type2.channel != ch) continue;
      if (filled == 0) hdr->time_us = (uint32_t)esp_timer_get_time();
      samples[filled++] = (uint16_t)r->type2.data;
      if (filled == kPacketSamples) {
        hdr->seq = seq++;
        // gdy nikt nie czyta portu, pakiet przepada (krótki timeout), a ADC działa dalej
        usb_serial_jtag_write_bytes(packet, sizeof(packet), pdMS_TO_TICKS(20));
        filled = 0;
      }
    }
  }
  adc_continuous_stop(h);
  adc_continuous_deinit(h);
  esp_log_level_set("*", ESP_LOG_WARN);
}

extern "C" void app_main() {
  usb_serial_jtag_driver_config_t ucfg = {};
  ucfg.tx_buffer_size = 16384;
  ucfg.rx_buffer_size = 256;
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&ucfg));
  usb_serial_jtag_vfs_use_driver();
  setvbuf(stdout, nullptr, _IONBF, 0);
  xTaskCreate(command_task, "cmd", 3072, nullptr, 5, nullptr);

  printf("\n=== Rejestrator mikrofonu ADC, %d Hz. Komendy: R (auto), R<0-6>, S ===\n", kSampleHz);
  while (true) {
    int cmd = g_cmd_channel;
    if (cmd == -1 || (cmd >= 0 && cmd <= kMaxChannel)) {
      int ch = cmd >= 0 ? cmd : g_auto_channel;
      g_cmd_channel = -2;
      if (ch < 0) {
        printf("Brak kanału auto - podaj R<n>\n");
        continue;
      }
      record(ch);   // wraca po S albo nowej komendzie R
      if (g_cmd_channel == -3) g_cmd_channel = -2;
      continue;
    }
    if (cmd == -3) g_cmd_channel = -2;
    scan_once();
    for (int i = 0; i < 20 && g_cmd_channel == -2; i++) vTaskDelay(pdMS_TO_TICKS(100));
  }
}
