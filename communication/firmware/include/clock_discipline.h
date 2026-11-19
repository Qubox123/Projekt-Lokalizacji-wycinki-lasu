#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>

// A bounded, allocation-free model for the local->gateway time conversion.
// offset_us = gateway_time - sensor_time. Offset slope [us/s] = ppm.
// This reduces measurement noise and models oscillator drift, but DOES NOT
// calibrate radio TX/RX timestamp bias or establish true TDOA accuracy.
class ClockDiscipline {
public:
  static constexpr std::size_t kCapacity = 16;
  static constexpr std::int64_t kMaxAgeUs = 180000000LL;

  bool add(std::int64_t local_rx_us, std::int64_t offset_us,
           std::int64_t estimated_rtt_us) {
    if (estimated_rtt_us < 0 || estimated_rtt_us > 1000000LL ||
        (count_ && local_rx_us <= samples_[count_ - 1].local_us)) {
      return false;
    }
    if (count_ == kCapacity) {
      for (std::size_t i = 1; i < count_; ++i) samples_[i - 1] = samples_[i];
      --count_;
    }
    samples_[count_++] = {local_rx_us, offset_us, estimated_rtt_us};
    return true;
  }

  bool fresh(std::int64_t local_now_us) const {
    return count_ && local_now_us >= samples_[count_ - 1].local_us &&
           local_now_us - samples_[count_ - 1].local_us <= kMaxAgeUs;
  }

  // Only use for fresh() timestamps. Caller may display stale predictions
  // for diagnostics, but should not label them synchronized events.
  std::int64_t corrected(std::int64_t local_now_us) const {
    return local_now_us + offsetAt(local_now_us);
  }

  std::int64_t offsetAt(std::int64_t local_now_us) const {
    if (!count_) return 0;
    const Fit fit = estimate();
    const double dt_s = static_cast<double>(local_now_us - fit.anchor_us) / 1000000.0;
    return static_cast<std::int64_t>(std::llround(fit.offset_us + fit.slope_ppm * dt_s));
  }

  double offsetSlopePpm() const { return estimate().slope_ppm; }
  std::size_t sampleCount() const { return count_; }

private:
  struct Sample {
    std::int64_t local_us;
    std::int64_t offset_us;
    std::int64_t rtt_us;
  };
  struct Fit {
    std::int64_t anchor_us;
    double offset_us;
    double slope_ppm;
  };
  Sample samples_[kCapacity]{};
  std::size_t count_ = 0;

  Fit estimate() const {
    if (!count_) return {0, 0.0, 0.0};

    // Prefer samples with smaller RTT: congestion delays often affect them
    // less. This is NOT a correction for directional delay asymmetry.
    std::size_t idx[kCapacity];
    for (std::size_t i = 0; i < count_; ++i) idx[i] = i;
    std::sort(idx, idx + count_, [this](std::size_t a, std::size_t b) {
      return samples_[a].rtt_us < samples_[b].rtt_us;
    });
    const std::size_t used = std::min<std::size_t>(count_, 8);
    // Use the most recently accepted measurement as a convenient anchor.
    const std::int64_t anchor = samples_[count_ - 1].local_us;

    double x_sum = 0.0, y_sum = 0.0;
    double min_x = 1e99, max_x = -1e99;
    for (std::size_t j = 0; j < used; ++j) {
      const Sample& s = samples_[idx[j]];
      const double x = static_cast<double>(s.local_us - anchor) / 1000000.0;
      x_sum += x;
      y_sum += static_cast<double>(s.offset_us);
      min_x = std::min(min_x, x);
      max_x = std::max(max_x, x);
    }
    const double mean_x = x_sum / used;
    const double mean_y = y_sum / used;
    if (used < 4 || max_x - min_x < 90.0) {
      // Too little information to estimate frequency error reliably.
      return {anchor, mean_y, 0.0};
    }

    double covariance = 0.0, variance = 0.0;
    for (std::size_t j = 0; j < used; ++j) {
      const Sample& s = samples_[idx[j]];
      const double x = static_cast<double>(s.local_us - anchor) / 1000000.0 - mean_x;
      const double y = static_cast<double>(s.offset_us) - mean_y;
      covariance += x * y;
      variance += x * x;
    }
    if (variance < 1e-9) return {anchor, mean_y, 0.0};
    const double slope = covariance / variance;
    // Implausible slopes mean the noisy samples cannot establish drift.
    if (std::abs(slope) > 100.0) return {anchor, mean_y, 0.0};
    return {anchor, mean_y - slope * mean_x, slope};
  }
};
