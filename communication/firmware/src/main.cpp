// POC LAB: SYNC dwukierunkowy XIAO ESP32-S3 + Wio-SX1262 (RadioLib).
// Nie jest to jeszcze precyzyjna synchronizacja do lokalizacji TDOA.
#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <esp_timer.h>
#include "protocol.h"
#include "sync_math.h"

#ifndef NODE_ID
#error "Ustaw NODE_ID=0 (gateway), 1,2 lub 3 (sensor)"
#endif
static_assert(NODE_ID <= 3, "NODE_ID musi byc 0..3");

// B2B pinout XIAO ESP32-S3 + Wio-SX1262. Zweryfikuj z zakupioną rewizją!
static constexpr int PIN_SCK=7, PIN_MISO=8, PIN_MOSI=9;
static constexpr int PIN_NSS=41, PIN_DIO1=39, PIN_RST=42, PIN_BUSY=40;
static constexpr int PIN_RF_SWITCH=38;

SX1262 radio = new Module(PIN_NSS, PIN_DIO1, PIN_RST, PIN_BUSY);
volatile bool rxPending = false;
volatile int64_t rxIrqTime = 0;
void IRAM_ATTR onRadioRx() {
  rxIrqTime = esp_timer_get_time();
  rxPending = true;
}

int64_t nextSyncDueUs = 3000000LL + (NODE_ID > 0 ? (NODE_ID-1)*3000000LL : 0);
int64_t lastEventUs = 0;
int64_t lastCorrectionUs = 0;
int64_t offsetUs = 0; // czas centrali - czas węzła
bool hasSync = false;
uint16_t nextSeq = 0;
uint16_t pendingSeq = 0;
int64_t pendingT1 = 0;

void armReceive() {
  digitalWrite(PIN_RF_SWITCH, HIGH); // Wio RF_SW: HIGH RX, LOW TX
  rxPending = false;
  const int16_t status = radio.startReceive();
  if (status != RADIOLIB_ERR_NONE) {
    Serial.printf("RX error: %d\n", status);
  }
}

// t1/t3 to czasy SOFTWAROWE pobrane tuż przed wywołaniem transmit().
// Nie są to precyzyjne znaczniki chwili rozpoczęcia emisji w SX1262.
void sendFrame(Frame& f, bool stampTx) {
  radio.standby();
  digitalWrite(PIN_RF_SWITCH, LOW);
  if (stampTx) {
    if (f.type == SYNC_REQ) f.t1 = esp_timer_get_time();
    if (f.type == SYNC_REPLY) f.t3 = esp_timer_get_time();
  }
  int16_t status = radio.transmit(reinterpret_cast<uint8_t*>(&f), sizeof(f));
  if (status != RADIOLIB_ERR_NONE) Serial.printf("TX error: %d\n", status);
  armReceive();
}

void processFrame(const Frame& f, int64_t rxTime) {
  if (!validFrame(f) || f.dst != NODE_ID) return;
#if NODE_ID == 0
  if (f.type == SYNC_REQ && f.src >= 1 && f.src <= 3) {
    Frame reply = makeFrame(SYNC_REPLY, 0, f.src, f.seq);
    reply.t1 = f.t1; // lokalny czas wysyłki sensora
    reply.t2 = rxTime; // lokalny czas odebrania gateway
    sendFrame(reply, true);
    Serial.printf("SYNC_REPLY for node=%u seq=%u\n", f.src, f.seq);
  } else if (f.type == TEST_EVENT) {
    Serial.printf("EVENT node=%u seq=%u local_us=%lld corrected_us=%lld rssi=%.1f\n",
                  f.src, f.seq, (long long)f.t1, (long long)f.t2, radio.getRSSI());
  }
#else
  if (f.type == SYNC_REPLY && f.src == 0 && f.seq == pendingSeq && pendingT1 != 0) {
    int64_t t1 = f.t1;    // czas sensora przy SYNC_REQ
    int64_t t2 = f.t2;    // czas gateway przy odbiorze
    int64_t t3 = f.t3;    // czas gateway przy SYNC_REPLY
    int64_t t4 = rxTime;  // czas sensora przy odbiorze odpowiedzi
    if (t1 != pendingT1) return;
    const SyncEstimate measurement = estimateSync(t1, t2, t3, t4);
    const int64_t theta = measurement.offset_us;
    const int64_t rtt = measurement.rtt_us;
    if (rtt < 0 || rtt > 1000000) {
      Serial.printf("Rejected sample: estimated RTT=%lld us\n", (long long)rtt);
      return;
    }
    offsetUs = theta;
    lastCorrectionUs = t4;
    hasSync = true;
    pendingT1 = 0;
    Serial.printf("SYNC node=%d offset=%lld us rtt_est=%lld us (UNCALIBRATED)\n",
                  NODE_ID, (long long)offsetUs, (long long)rtt);
  }
#endif
}

void setup() {
  Serial.begin(115200);
  delay(1200);
  Serial.printf("NODE_ID=%d, sync PoC\n", NODE_ID);
  pinMode(PIN_RF_SWITCH, OUTPUT);
  digitalWrite(PIN_RF_SWITCH, HIGH);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_NSS);
  // 868 MHz, BW125, SF7, CR4/5, private sync word, 10 dBm, TCXO 1.8V.
  const int16_t status = radio.begin(868.0, 125.0, 7, 5, 0x12, 10, 8, 1.8);
  if (status != RADIOLIB_ERR_NONE) {
    Serial.printf("Radio init failed: %d. Check board pinout, RF switch, TCXO.\n", status);
    while (true) delay(1000);
  }
  radio.setPacketReceivedAction(onRadioRx);
  armReceive();
  Serial.println("Radio ready");
}

void loop() {
  if (rxPending) {
    noInterrupts();
    const int64_t at = rxIrqTime;
    rxPending = false;
    interrupts();
    Frame f = {};
    const size_t len = radio.getPacketLength();
    const int16_t status = (len == sizeof(f)) ?
      radio.readData(reinterpret_cast<uint8_t*>(&f), sizeof(f)) : -999;
    // Radio znowu ustawi się w RX po przetworzeniu (albo w sendFrame()).
    if (status == RADIOLIB_ERR_NONE) processFrame(f, at);
    else Serial.printf("RX invalid len=%u status=%d\n", unsigned(len), status);
    armReceive();
  }
#if NODE_ID != 0
  const int64_t now = esp_timer_get_time();
  // Deterministyczne sloty, żeby zmniejszyć kolizje trzech węzłów.
  // Sloty rozruchowe: 3/6/9 s. W realnym systemie zastąpić harmonogramem.
  if (now >= nextSyncDueUs) {
    nextSyncDueUs = now + 30000000LL;
    Frame req = makeFrame(SYNC_REQ, NODE_ID, 0, ++nextSeq);
    // Pending wartość aktualizowana po ustawieniu t1.
    radio.standby();
    digitalWrite(PIN_RF_SWITCH, LOW);
    req.t1 = esp_timer_get_time();
    pendingT1 = req.t1;
    pendingSeq = req.seq;
    int16_t status = radio.transmit(reinterpret_cast<uint8_t*>(&req), sizeof(req));
    if (status != RADIOLIB_ERR_NONE) Serial.printf("Sync TX error=%d\n", status);
    armReceive();
  }
  if (hasSync && now-lastEventUs > 20000000LL) {
    lastEventUs = now;
    Frame evt = makeFrame(TEST_EVENT, NODE_ID, 0, ++nextSeq);
    evt.t1 = now;                // sztuczne zdarzenie, jeszcze bez mikrofonu
    evt.t2 = now + offsetUs;     // korekta offsetu, bez kompensacji dryftu
    evt.t3 = lastCorrectionUs;   // diagnostyka wieku synchronizacji
    sendFrame(evt, false);
  }
#endif
  delay(2);
}
