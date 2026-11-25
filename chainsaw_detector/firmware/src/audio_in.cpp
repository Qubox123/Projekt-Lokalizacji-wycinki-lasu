#include "audio_in.h"

#include <stdint.h>

#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "feature_config.h"
#include "node_config.h"

#if defined(MIC_PDM)
#include "driver/i2s_pdm.h"
#else
#include "driver/i2s_std.h"
#endif

static i2s_chan_handle_t rx;

void audio_init() {
  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  // ok. 0,4 s bufora DMA: tyle może trwać liczenie cech i sieci bez gubienia próbek
  chan.dma_desc_num = 8;
  chan.dma_frame_num = 800;
  ESP_ERROR_CHECK(i2s_new_channel(&chan, nullptr, &rx));

#if defined(MIC_PDM)
  // XIAO ESP32-S3 Sense: wbudowany mikrofon PDM, sprzętowa konwersja PDM -> PCM 16 bit
  i2s_pdm_rx_config_t cfg = {
      .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(CS_SAMPLE_RATE),
      .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
      .gpio_cfg = {.clk = (gpio_num_t)MIC_PDM_CLK, .din = (gpio_num_t)MIC_PDM_DATA,
                   .invert_flags = {.clk_inv = false}},
  };
  ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx, &cfg));
#else
  // INMP441 / ICS-43434: 24 bity wyrównane do lewej w 32-bitowym slocie.
  // Pin L/R mikrofonu do GND -> lewy kanał.
  i2s_std_config_t cfg = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(CS_SAMPLE_RATE),
      .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
      .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = (gpio_num_t)MIC_SCK,
                   .ws = (gpio_num_t)MIC_WS, .dout = I2S_GPIO_UNUSED,
                   .din = (gpio_num_t)MIC_SD,
                   .invert_flags = {.mclk_inv = false, .bclk_inv = false, .ws_inv = false}},
  };
  cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;
  ESP_ERROR_CHECK(i2s_channel_init_std_mode(rx, &cfg));
#endif
  ESP_ERROR_CHECK(i2s_channel_enable(rx));
}

void audio_read(float* out, size_t n) {
#if defined(MIC_PDM)
  using sample_t = int16_t;
  const float scale = 1.0f / 32768.0f;
#else
  using sample_t = int32_t;
  // Całe 32-bitowe słowo dzielone przez 2^31: bez ręcznego przesuwania bitów,
  // które przy złym przesunięciu dawało w mic_test/ ok. 4-bitowy, przesterowany sygnał.
  const float scale = 1.0f / 2147483648.0f;
#endif
  static sample_t buf[512];
  size_t done = 0;
  while (done < n) {
    size_t want = n - done;
    if (want > 512) want = 512;
    size_t got = 0;
    ESP_ERROR_CHECK(i2s_channel_read(rx, buf, want * sizeof(sample_t), &got, portMAX_DELAY));
    got /= sizeof(sample_t);
    for (size_t i = 0; i < got; i++) out[done + i] = buf[i] * scale * MIC_GAIN;
    done += got;
  }
}
