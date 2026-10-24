# Single minimal-power LoRa transmission to check the radio chip responds.
# Safety limits (safe even with a missing/badly seated antenna):
# - lowest allowed EU868 power (2 dBm), verified before sending, abort otherwise
# - SF7 / 125 kHz, 4-byte payload -> ~30 ms on air, sent exactly once, no retries
# - radio put to sleep right after
#
# Run from repo root:  python3 esp32/tools/rawrun.py /dev/ttyACM1 esp32/tests/lora_tx_once.py

import time
import socket
from network import LoRa

FREQ = 868100000
TX_POWER = 2

lora = LoRa(mode=LoRa.LORA, region=LoRa.EU868, frequency=FREQ, tx_power=TX_POWER,
            bandwidth=LoRa.BW_125KHZ, sf=7, coding_rate=LoRa.CODING_4_5)

checks = [("tx_power", lora.tx_power(), TX_POWER),
          ("frequency", lora.frequency(), FREQ),
          ("sf", lora.sf(), 7)]
for name, got, want in checks:
    print("{}: {} (want {})".format(name, got, want))
if any(got != want for _, got, want in checks):
    print("ABORT: settings mismatch, nothing transmitted")
    lora.power_mode(LoRa.SLEEP)
    raise SystemExit

tx_done = []
lora.callback(trigger=LoRa.TX_PACKET_EVENT, handler=lambda l: tx_done.append(time.ticks_ms()))

s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
s.setblocking(False)
t0 = time.ticks_ms()
s.send(b"PING")
print("sent 1 packet, waiting for TX done ...")

while not tx_done and abs(time.ticks_diff(t0, time.ticks_ms())) < 2000:
    time.sleep_ms(5)

s.close()
lora.power_mode(LoRa.SLEEP)

if tx_done:
    print("RESULT: TX done after", abs(time.ticks_diff(t0, tx_done[0])), "ms -> radio chip responds")
else:
    print("RESULT: no TX done event within 2 s -> radio chip NOT responding")
