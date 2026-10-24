# Hardware smoke test for Pycom LoPy 1.0 on Expansion Board 3.0.
# - prints board info to the serial console
# - cycles the on-module RGB LED (red -> green -> blue)
# - prints the state of button S1 (P10) each tick: 1 = released, 0 = pressed.
# - blinks the expansion board user LED (P9, needs the LED jumper fitted)

import os
import gc
import time
import machine
import pycom
from machine import Pin

print("=== LoPy smoke test ===")
print("uname:     ", os.uname())
print("unique id: ", "".join("{:02x}".format(b) for b in machine.unique_id()))
print("free mem:  ", gc.mem_free())
print("files:     ", os.listdir("/flash"))

pycom.heartbeat(False)  # take control of the RGB LED

button = Pin("P10", mode=Pin.IN, pull=Pin.PULL_UP)
user_led = Pin("P9", mode=Pin.OUT)

COLORS = [(0x200000, "red"), (0x002000, "green"), (0x000020, "blue")]

i = 0
while True:
    color, name = COLORS[i % len(COLORS)]
    pycom.rgbled(color)
    user_led.toggle()
    print("tick", i, name, "button:", button())
    i += 1
    time.sleep(0.5)
