#pragma once
#include <Arduino.h>

// Wszystkie pakiety mają jednakową długość: ogranicza różnicę czasu na antenie.
static constexpr uint16_t PROTO_MAGIC = 0xB47A;
static constexpr uint8_t PROTO_VERSION = 1;
enum : uint8_t { SYNC_REQ = 1, SYNC_REPLY = 2, TEST_EVENT = 3 };

struct __attribute__((packed)) Frame {
  uint16_t magic;
  uint8_t version;
  uint8_t type;
  uint8_t src;
  uint8_t dst;
  uint16_t seq;
  int64_t t1;
  int64_t t2;
  int64_t t3;
};
static_assert(sizeof(Frame) == 32, "Unexpected packet size");

inline Frame makeFrame(uint8_t type, uint8_t src, uint8_t dst, uint16_t seq) {
  Frame f = {};
  f.magic = PROTO_MAGIC;
  f.version = PROTO_VERSION;
  f.type = type;
  f.src = src;
  f.dst = dst;
  f.seq = seq;
  return f;
}
inline bool validFrame(const Frame& f) {
  return f.magic == PROTO_MAGIC && f.version == PROTO_VERSION &&
         f.src <= 3 && f.dst <= 3;
}
