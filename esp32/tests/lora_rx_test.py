# Receive-only LoRa check for Pycom LoPy 1.0 (EU868).
# Never transmits, so it is safe to run even without an antenna attached.
# - initialises the LoRa radio in raw LoRa mode
# - prints the radio's EUI and settings
# - estimates the channel noise floor with ischannel_free()
# - listens for any LoRa packets on 868.1 MHz for LISTEN_S seconds
#
# Run from repo root:  ampy -p /dev/ttyACM1 run esp32/tests/lora_rx_test.py  (LISTEN_S must stay < ~10 s for ampy)
#   or:               python3 esp32/tools/rawrun.py /dev/ttyACM1 esp32/tests/lora_rx_test.py

import time
import socket
import ubinascii
from network import LoRa

FREQ = 868100000
LISTEN_S = 20

print("=== LoRa RX-only test ===")
lora = LoRa(mode=LoRa.LORA, region=LoRa.EU868, frequency=FREQ,
            bandwidth=LoRa.BW_125KHZ, sf=7, coding_rate=LoRa.CODING_4_5)
print("radio init:  OK")
print("EUI:        ", ubinascii.hexlify(lora.mac()).decode())
print("frequency:  ", lora.frequency())
print("sf / bw:    ", lora.sf(), "/", lora.bandwidth())

# Lowest threshold at which the channel still counts as "free" ~= noise floor.
try:
    floor = None
    for threshold in range(-140, -40, 5):
        if lora.ischannel_free(threshold):
            floor = threshold
            break
    print("noise floor: ~", floor, "dBm")
except Exception as e:
    print("noise floor: n/a (", e, ")")

s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
s.setblocking(False)
print("listening for", LISTEN_S, "s ...")
received = 0
end = time.time() + LISTEN_S
while time.time() < end:
    data = s.recv(256)
    if data:
        received += 1
        st = lora.stats()
        print("packet:", data, "rssi:", st.rssi, "snr:", st.snr)
    time.sleep_ms(50)
print("packets received:", received)
print("=== done ===")
