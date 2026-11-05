#pragma once
#include <cstdint>

// Funkcje czysto obliczeniowe - nie wymagają Arduino/ESP32/LoRa.
// offset = czas centrali - czas sensora; jednostki: mikrosekundy.
struct SyncEstimate {
    std::int64_t offset_us;
    std::int64_t rtt_us;
};

constexpr SyncEstimate estimateSync(
    std::int64_t t1, std::int64_t t2,
    std::int64_t t3, std::int64_t t4
) noexcept {
    return {
        ((t2 - t1) + (t3 - t4)) / 2,
        (t4 - t1) - (t3 - t2)
    };
}
