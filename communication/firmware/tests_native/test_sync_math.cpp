#include "sync_math.h"
#include <cassert>
#include <iostream>

int main() {
    // Sensor spieszy się o 1 ms, symetryczny transfer.
    {
        const auto m = estimateSync(11000, 11000, 13000, 15000);
        assert(m.offset_us == -1000);
        assert(m.rtt_us == 2000);
    }
    // Zegary idealne, opóźnienia 54 ms i 46 ms -> błąd +4 ms.
    {
        const auto m = estimateSync(1000000, 1054000, 1069000, 1115000);
        assert(m.offset_us == 4000);
        assert(m.rtt_us == 100000);
    }
    // Niedorzeczna sekwencja timestampów, RTT < 0, odrzucana w firmware.
    {
        const auto m = estimateSync(1000, 2000, 3000, 1100);
        assert(m.rtt_us == -900);
    }
    std::cout << "PASS: 3 native C++ sync-math tests\n";
}
