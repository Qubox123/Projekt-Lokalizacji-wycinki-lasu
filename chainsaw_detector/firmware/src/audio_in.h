// Odczyt mikrofonu przez I2S, wynik jako float w zakresie [-1, 1] przy 16 kHz,
// czyli w tej samej skali co soundfile.read() w datasets.load_audio.
#pragma once

#include <stddef.h>

void audio_init();
// Blokuje, aż przyjdzie n próbek.
void audio_read(float* out, size_t n);
