# Firmware i kopie zapasowe

Binarek firmware'u i kopii flasha **nie trzymamy w repozytorium** (`*.bin` jest w `.gitignore`).
Kopie są specyficzne dla jednej płytki i mogą zawierać dane logowania WiFi/TTN.

## Wersja

| | |
|---|---|
| Firmware | Pycom MicroPython **1.18.3** (`LoPy-1.18.3`) |
| Źródło | [GitHub release v1.18.3](https://github.com/pycom/pycom-micropython-sigfox/releases/tag/v1.18.3), plik `LoPy-1.18.3-application.elf` |
| SHA-256 ELF | `5ae34b9c917a3c9e9706974bcb3b10d2ccb34f64605e053c896fe1a56e2bbe1b` |

Serwer `software.pycom.io` (oficjalny updater) już nie działa — Pycom zakończył działalność.
Gotowe paczki `.tar.gz` nie są dostępne; na GitHubie są tylko pliki ELF.

## Tryb wgrywania (bootloader)

1. Zamknij wszystkie programy używające portu.
2. Połącz przewodem **G23 (P2) z GND** na Expansion Board.
3. Naciśnij reset — dioda RGB nie miga.
4. Po zakończeniu usuń przewód i naciśnij reset.

Sprawdzenie połączenia:

```bash
esptool.py --chip esp32 -p /dev/ttyACM1 -b 115200 --before no_reset --after no_reset flash_id
```

## Kopia zapasowa całego flasha (zawsze przed wgrywaniem)

```bash
mkdir -p esp32/backup
esptool.py --chip esp32 -p /dev/ttyACM1 -b 115200 --before no_reset --after no_reset \
  read_flash 0 0x400000 esp32/backup/lopy-full-flash-$(date +%F).bin     # ~6,5 min
esptool.py --chip esp32 -p /dev/ttyACM1 -b 115200 --before no_reset --after no_reset \
  verify_flash 0 esp32/backup/lopy-full-flash-$(date +%F).bin
```

Przywrócenie: `write_flash 0 <plik>.bin` z tymi samymi opcjami.

## Układ flasha (1.18.3, 4 MB)

| Partycja | Offset | Rozmiar |
|---|---|---|
| bootloader | `0x001000` | |
| tablica partycji | `0x008000` | |
| nvs | `0x009000` | `0x007000` |
| factory (aplikacja) | `0x010000` | `0x180000` |
| otadata (boot info Pycom) | `0x190000` | `0x001000` |
| ota_0 | `0x1a0000` | `0x180000` |
| dummy | `0x320000` | `0x010000` |
| fs (`/flash`) | `0x380000` | `0x07f000` |
| config (LoRa MAC itd.) | `0x3ff000` | `0x001000` |

## Wgrywanie aplikacji z ELF

Tylko jeśli obecny firmware jest uszkodzony lub zmieniamy wersję. Bootloader i tablicę
partycji zostawiamy bez zmian.

```bash
esptool.py --chip esp32 elf2image --flash_mode dio --flash_freq 80m --flash_size 4MB \
  -o LoPy-1.18.3-app.bin LoPy-1.18.3-application.elf
esptool.py image_info --version 2 LoPy-1.18.3-app.bin    # checksum i hash: valid
esptool.py --chip esp32 -p /dev/ttyACM1 -b 115200 --before no_reset --after no_reset \
  write_flash 0x10000 LoPy-1.18.3-app.bin
```

Uwaga: wersje 1.20.x mogą wymagać innego układu partycji — nie testowane.
