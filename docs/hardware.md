# Sprzęt

## Moduł i płytka

- **Pycom LoPy 1.0**: ESP32-D0WDQ6, 4 MB flash, radio LoRa **Semtech SX1272** (863–1020 MHz).
- **Expansion Board 3.0**: USB-serial przez PIC (`04d8:ef98`), port `/dev/ttyACM*`.
- Firmware: Pycom MicroPython **1.18.3** — szczegóły w [flashing.md](flashing.md).

Moduł wkłada się diodą RGB i przyciskiem reset w stronę złącza USB płytki.

## Piny

| Element | Pin | Uwagi |
|---|---|---|
| Dioda RGB (na module) | — | `pycom.heartbeat(False)`, potem `pycom.rgbled(0xRRGGBB)` |
| Przycisk S1 | `P10` | `Pin.PULL_UP`; 1 = puszczony, 0 = wciśnięty |
| Dioda użytkownika | `P9` | wymaga założonej zworki „LED”; pin niepotwierdzony w dokumentacji |
| Tryb wgrywania firmware'u | `P2` / G23 | zwarcie do GND + reset |

`P13`–`P18` to piny wyłącznie wejściowe **bez wewnętrznych rezystorów pull-up/down**
— niepodłączone dają losowe odczyty.

Pycom nie opublikował schematu Expansion Board 3.0; przypisania pinów pochodzą z forum
i z testów.

## Antena

- Antena LoRa 868 MHz do złącza u.FL **LoRa na module** (obok diody RGB), nie do złącza WiFi.
- Nie nadawać z dużą mocą bez anteny. Krótki test 2 dBm (`esp32/tests/lora_tx_once.py`) jest bezpieczny.
- Szybki test anteny bez nadawania: w paśmie 925–928 MHz (downlink stacji GSM/LTE 900)
  sprawny odbiór pokazuje ok. −65…−75 dBm, czyli ~40 dB ponad szum.

## Zawieszone radio SX1272

Znany problem LoPy1 ([nota Pycom](https://docs.pycom.io/datasheets/notes/)): radio SX1272
potrafi się zawiesić, szczególnie po długiej pracy lub przy niestabilnym zasilaniu.

Objawy:
- `lora.ischannel_free()` daje płaskie −140 dBm na każdej częstotliwości,
- po `send()` nie przychodzi zdarzenie `TX_PACKET_EVENT`,
- `lora.power_mode(LoRa.SLEEP)` zwraca `OSError: the requested operation failed`.

**Przycisk reset ani `machine.reset()` nie resetują radia** — trzeba odłączyć zasilanie
(USB) na ~10 s. W urządzeniu docelowym trzeba przewidzieć okresowe odcięcie zasilania
radia/modułu (np. raz na dobę) albo wykrywanie tego stanu i power-cycle.

## Identyfikator LoRa (DevEUI)

Na tej płytce `lora.mac()` zwraca `ffffffffffffffff` — blok konfiguracyjny (`0x3FF000`)
został wyczyszczony przy pełnym kasowaniu flasha, a serwery Pycom, które go odtwarzały,
już nie działają. Dla surowego LoRa nie ma to znaczenia. Dla LoRaWAN/TTN należy nadać
każdej płytce własny, unikalny 8-bajtowy EUI (np. zapisując go do `/flash/sys/lpwan.mac`)
i **nie commitować** go do repozytorium.
