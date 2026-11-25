#include "features.h"

#include <math.h>
#include <string.h>

static_assert(CS_N_FFT == 512, "FFT ma stałą długość 512 (kLog2N)");
static constexpr int kBins = CS_N_FFT / 2 + 1;
static constexpr int kLog2N = 9;

void Highpass::process(const float* in, float* out, int n) {
  const float b0 = cs_highpass_coef[0], b1 = cs_highpass_coef[1], b2 = cs_highpass_coef[2];
  const float a1 = cs_highpass_coef[3], a2 = cs_highpass_coef[4];
  for (int i = 0; i < n; i++) {
    float x = in[i];
    float y = b0 * x + z1_;
    z1_ = b1 * x - a1 * y + z2_;
    z2_ = b2 * x - a2 * y;
    out[i] = y;
  }
}

// FFT radix-2 bez esp-dsp, żeby kod dało się sprawdzić na PC (tools/check_features.py).
// Sygnał jest rzeczywisty, więc 512 próbek liczy się jedną zespoloną FFT o długości 256
// (parzyste próbki jako część rzeczywista, nieparzyste jako urojona) i rozplata wynik.
// To połowa obliczeń - ważne na ESP32-C6, który nie ma sprzętowego float.
static constexpr int kHalf = CS_N_FFT / 2;
static float g_window[CS_N_FFT];
static float g_cos[kHalf], g_sin[kHalf];           // exp(-2*pi*i*k/N_FFT)
static uint16_t g_bitrev[kHalf];
static bool g_tables_ready = false;

static void init_tables() {
  const double pi = 3.14159265358979323846;
  for (int n = 0; n < CS_N_FFT; n++) g_window[n] = (float)(0.5 - 0.5 * cos(2.0 * pi * n / CS_N_FFT));
  for (int n = 0; n < kHalf; n++) {
    int r = 0;
    for (int b = 0; b < kLog2N - 1; b++) r |= ((n >> b) & 1) << (kLog2N - 2 - b);
    g_bitrev[n] = (uint16_t)r;
  }
  for (int k = 0; k < kHalf; k++) {
    g_cos[k] = (float)cos(2.0 * pi * k / CS_N_FFT);
    g_sin[k] = (float)-sin(2.0 * pi * k / CS_N_FFT);
  }
  g_tables_ready = true;
}

static void fft_half(float* re, float* im) {
  for (int i = 0; i < kHalf; i++) {
    int j = g_bitrev[i];
    if (j > i) {
      float t = re[i]; re[i] = re[j]; re[j] = t;
      t = im[i]; im[i] = im[j]; im[j] = t;
    }
  }
  for (int len = 2; len <= kHalf; len <<= 1) {
    int half = len >> 1, step = CS_N_FFT / len;   // twiddle exp(-2*pi*i*k/len)
    for (int i = 0; i < kHalf; i += len) {
      for (int k = 0; k < half; k++) {
        float wr = g_cos[k * step], wi = g_sin[k * step];
        int a = i + k, b = a + half;
        float tr = re[b] * wr - im[b] * wi;
        float ti = re[b] * wi + im[b] * wr;
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr; im[a] += ti;
      }
    }
  }
}

// |X[k]|^2 / N_FFT dla k = 0..N_FFT/2 z rzeczywistej ramki x (już po oknie).
static void power_spectrum(const float* x, float* power) {
  static float re[kHalf], im[kHalf];
  for (int n = 0; n < kHalf; n++) {
    re[n] = x[2 * n];
    im[n] = x[2 * n + 1];
  }
  fft_half(re, im);
  const float inv = 1.0f / CS_N_FFT;
  float x0 = re[0] + im[0], xn = re[0] - im[0];
  power[0] = x0 * x0 * inv;
  power[kHalf] = xn * xn * inv;
  for (int k = 1; k < kHalf; k++) {
    float zr = re[k], zi = im[k], cr = re[kHalf - k], ci = -im[kHalf - k];
    float er = 0.5f * (zr + cr), ei = 0.5f * (zi + ci);   // widmo próbek parzystych
    float orr = 0.5f * (zi - ci), oi = -0.5f * (zr - cr); // nieparzystych
    float wr = g_cos[k], wi = g_sin[k];
    float xr = er + wr * orr - wi * oi;
    float xi = ei + wr * oi + wi * orr;
    power[k] = (xr * xr + xi * xi) * inv;
  }
}

void mel_power(const float* window, float* mel, int first_frame) {
  if (!g_tables_ready) init_tables();
  static float frame[CS_N_FFT], power[kBins];
  for (int f = first_frame; f < CS_N_FRAMES; f++) {
    const float* x = window + f * CS_HOP;
    for (int n = 0; n < CS_N_FFT; n++) frame[n] = x[n] * g_window[n];
    power_spectrum(frame, power);
    float* row = mel + f * CS_N_MELS;
    for (int m = 0; m < CS_N_MELS; m++) {
      const float* p = power + cs_mel_start[m];
      const float* w = cs_mel_weights + cs_mel_offset[m];
      float acc = 0.0f;
      for (int j = 0; j < cs_mel_len[m]; j++) acc += p[j] * w[j];
      row[m] = acc;
    }
  }
}

void mel_power_slide(const float* window, float* mel, bool have_previous) {
  // okno przesuwa się o CS_STREAM_HOP = całkowitą liczbę ramek, więc pierwsze ramki
  // nowego okna to ostatnie ramki poprzedniego - liczymy tylko nowe
  static_assert(CS_STREAM_HOP % CS_HOP == 0, "hop strumienia musi być wielokrotnością HOP");
  constexpr int shift = CS_STREAM_HOP / CS_HOP;
  if (!have_previous) {
    mel_power(window, mel, 0);
    return;
  }
  memmove(mel, mel + shift * CS_N_MELS, (CS_N_FRAMES - shift) * CS_N_MELS * sizeof(float));
  mel_power(window, mel, CS_N_FRAMES - shift);
}

void log_mel(const float* mel, const float* profile, float* out) {
  for (int f = 0; f < CS_N_FRAMES; f++) {
    for (int m = 0; m < CS_N_MELS; m++) {
      float v = mel[f * CS_N_MELS + m];
      if (profile) v = fmaxf(v - CS_SUBTRACT_ALPHA * profile[m], CS_SUBTRACT_FLOOR * v);
      out[f * CS_N_MELS + m] = logf(v + CS_LOG_EPS);
    }
  }
}

void NoiseTracker::update(const float* mel, float p_chainsaw) {
  float current[CS_N_MELS] = {};
  for (int f = 0; f < CS_N_FRAMES; f++)
    for (int m = 0; m < CS_N_MELS; m++) current[m] += mel[f * CS_N_MELS + m];
  for (int m = 0; m < CS_N_MELS; m++) current[m] /= CS_N_FRAMES;

  if (!ready_) {
    memcpy(profile_, current, sizeof(profile_));
    ready_ = true;
  } else if (p_chainsaw < CS_NOISE_UPDATE_BELOW) {
    for (int m = 0; m < CS_N_MELS; m++)
      profile_[m] = (1.0f - CS_NOISE_EMA) * profile_[m] + CS_NOISE_EMA * current[m];
  }
}
