#include "clock_discipline.h"
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <cstdio>

int main() {
  ClockDiscipline model;
  assert(!model.fresh(1000000));
  assert(!model.add(1000000, 0, -1));
  // Reference offset changes -24 us per second (sensor clock fast by 24 ppm).
  for (int i = 0; i < 16; ++i) {
    const std::int64_t t = 1000000LL + i * 30000000LL;
    const std::int64_t expected_offset = 350000LL - 24LL * 30LL * i;
    assert(model.add(t, expected_offset, 40000));
  }
  const std::int64_t future = 1000000LL + 480000000LL;
  const std::int64_t expected = future + 350000LL - 24LL * 480LL;
  assert(std::llabs(model.corrected(future) - expected) <= 2);
  assert(std::abs(model.offsetSlopePpm() + 24.0) < 0.01);
  assert(model.fresh(future));
  assert(!model.fresh(future + 181000000LL));

  // High-RTT outlier should be excluded from the best-RTT subset.
  assert(model.add(1000000LL + 16 * 30000000LL, 900000LL, 900000));
  assert(std::llabs(model.corrected(future) - expected) <= 2);

  ClockDiscipline single;
  assert(single.add(5000000, -100000, 120000));
  assert(single.corrected(5000000) == 4900000);
  assert(!single.add(5000000, -200000, 120000));
  std::puts("PASS: native clock discipline tests");
}
