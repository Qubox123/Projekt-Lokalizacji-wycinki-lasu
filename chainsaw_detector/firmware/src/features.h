// Ekstrakcja cech 1:1 z features.py: filtr HP -> okno Hanna -> FFT -> bank mel -> log.
#pragma once

#include "feature_config.h"

// Biquad (sosfilt, postać transponowana II). Stan ciągły między wywołaniami,
// tak jak w infer.py, gdzie filtr działa na całym strumieniu.
class Highpass {
 public:
  void process(const float* in, float* out, int n);

 private:
  float z1_ = 0.0f, z2_ = 0.0f;
};

// Moc w pasmach mel dla okna CS_WINDOW_SAMPLES (już po filtrze HP).
// mel: CS_N_FRAMES * CS_N_MELS, wierszami po ramkach; liczone od ramki first_frame.
void mel_power(const float* window, float* mel, int first_frame = 0);

// To samo dla okna przesuniętego o CS_STREAM_HOP: przesuwa stare ramki w mel
// i liczy tylko nowe (o połowę mniej FFT). have_previous = false -> całe okno.
void mel_power_slide(const float* window, float* mel, bool have_previous);

// log(max(P - ALPHA*N, FLOOR*P) + EPS); profile == nullptr -> bez odejmowania.
void log_mel(const float* mel, const float* profile, float* out);

// Profil tła jak NoiseTracker w features.py.
class NoiseTracker {
 public:
  bool ready() const { return ready_; }
  const float* profile() const { return ready_ ? profile_ : nullptr; }
  void update(const float* mel, float p_chainsaw);

 private:
  float profile_[CS_N_MELS] = {};
  bool ready_ = false;
};
