# Węzeł ESP32 (Pycom LoPy 1.0)

Kod działający na węźle w lesie: Pycom LoPy 1.0 (ESP32 + Semtech SX1272, LoRa EU868)
na płytce Expansion Board 3.0. Sprzęt, piny i znane problemy: [docs/hardware.md](../docs/hardware.md).
Wgrywanie firmware'u i kopie zapasowe: [docs/flashing.md](../docs/flashing.md).

## Struktura

```
esp32/
  device/          tylko to, co trafia na /flash płytki
    main.py        uruchamiany przy każdym starcie (obecnie: test LED / przycisku)
    config.py      lokalna konfiguracja z sekretami (gitignore; nie commitować)
  tests/           skrypty testowe sprzętu, uruchamiane bez zapisu na płytkę
  tools/           narzędzia po stronie PC
    rawrun.py      uruchamia skrypt na płytce bez limitu czasu ampy
  requirements.txt narzędzia PC (ampy, esptool, pyserial)
```

## Przygotowanie

```bash
pip install --user -r esp32/requirements.txt
```

Użytkownik musi być w grupie `dialout`. Płytka zgłasza się jako `/dev/ttyACM*`
(USB `04d8:ef98`, „Expansion3”). Sprawdzenie, który port:

```bash
udevadm info -q property -n /dev/ttyACM1 | grep ID_MODEL=   # powinno być Expansion3
```

W przykładach poniżej port to `/dev/ttyACM1`; u Ciebie może być inny.

## Wgrywanie kodu

Polecenia uruchamiaj z katalogu głównego repozytorium. Zamknij wcześniej picocom/screen,
bo port może być otwarty tylko przez jeden program.

```bash
ampy -p /dev/ttyACM1 put esp32/device/main.py /flash/main.py
ampy -p /dev/ttyACM1 reset --hard        # samo `reset` NIE uruchamia main.py
picocom -b 115200 /dev/ttyACM1           # konsola; wyjście: Ctrl-A, Ctrl-X
```

W konsoli Ctrl-C zatrzymuje `main.py` i daje prompt `>>>`.

## Testy sprzętu

| Skrypt | Co sprawdza | Nadaje? |
|---|---|---|
| `device/main.py` | konsola, dioda RGB, dioda P9, przycisk S1 (P10) | nie |
| `tests/lora_rx_test.py` | inicjalizacja radia, poziom szumu, nasłuch pakietów | nie |
| `tests/lora_tx_once.py` | jeden pakiet 2 dBm, ~31 ms; czy radio zgłasza „TX done” | tak, minimalnie |

```bash
python3 esp32/tools/rawrun.py /dev/ttyACM1 esp32/tests/lora_rx_test.py
python3 esp32/tools/rawrun.py /dev/ttyACM1 esp32/tests/lora_tx_once.py
```

`ampy run` przerywa po ok. 10 s, dlatego dłuższe testy uruchamiaj przez `rawrun.py`.

Oczekiwane wyniki dla sprawnej płytki: poziom szumu ok. −105…−115 dBm (nie płaskie −140)
oraz `TX done after ~33 ms`. Jeśli radio wygląda na martwe, najpierw **odłącz USB na ~10 s**
— patrz [docs/hardware.md](../docs/hardware.md#zawieszone-radio-sx1272).
