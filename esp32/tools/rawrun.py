#!/usr/bin/env python3
"""Run a MicroPython script on the board via raw REPL and stream its output.

Unlike `ampy run`, there is no fixed ~10 s timeout, so long tests work.
The script is not saved to the board's flash.

Usage: python3 esp32/tools/rawrun.py /dev/ttyACM1 esp32/tests/lora_rx_test.py [timeout_s]
"""
import sys
import time

import serial


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    port, path = sys.argv[1], sys.argv[2]
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 120
    code = open(path, "rb").read()

    s = serial.Serial(port, 115200, timeout=0.2)
    s.write(b"\r\x03\x03")  # interrupt whatever is running (e.g. main.py)
    time.sleep(0.3)
    s.read(10000)
    s.write(b"\x01")  # enter raw REPL
    time.sleep(0.3)
    s.read(10000)
    for i in range(0, len(code), 256):
        s.write(code[i:i + 256])
        time.sleep(0.01)
    s.write(b"\x04")  # execute

    out = b""
    end = time.time() + timeout
    while time.time() < end:
        chunk = s.read(512)
        if chunk:
            out += chunk
            sys.stdout.write(chunk.decode(errors="replace"))
            sys.stdout.flush()
            if out.count(b"\x04") >= 2:  # end of stdout + end of stderr
                break
    else:
        print("\n[rawrun] timeout after", timeout, "s")
    s.write(b"\x02")  # back to the normal REPL
    sys.exit(1 if b"Traceback" in out or not out.count(b"\x04") >= 2 else 0)


if __name__ == "__main__":
    main()
