# Synchronizacja LoRa — prototyp laboratoryjny (IoT AGH)

## Cel
3 węzły pomiarowe XIAO ESP32-S3/Wio-SX1262 i 1 centralny. Prototyp nie wymaga gotowego klasyfikatora ML, mikrofonów ani backendu. Wszystkie zdarzenia w firmware są **syntetyczne**.

## Uruchomienie symulatora na Beaglinuxie

```bash
python3 simulator/clock_sync.py --duration 300 --interval 30
python3 -m unittest discover -s tests -v
```

Dane w symulatorze są przykładowe, nie mierzone. Obliczamy θ = ((t2-t1)+(t3-t4))/2 (czas centrali minus czas węzła). Zmienne opóźnienia i asymetria powodują błąd nawet przy idealnych zegarach. Dryft wymaga wielu kolejnych pomiarów i ewentualnie regresji; na etapie pierwszego firmware stosujemy tylko aktualny offset.

## Uruchomienie na XIAO ESP32-S3 + Wio-SX1262

Zainstaluj PlatformIO w VS Code; w katalogu `firmware/`:

```bash
pio run -e gateway
pio run -e node1
# każdą płytkę podłącz oddzielnie i wgrywaj właściwy wariant
pio run -e gateway -t upload
pio run -e node1 -t upload
pio device monitor -b 115200
```

Zestawy z różnymi wersjami Wio-SX1262 mogą mieć różne wyprowadzenia. W `main.cpp` wpisano **przykładowe** B2B GPIO (NSS=41, DIO1=39, RESET=42, BUSY=40, SCK=7, MISO=8, MOSI=9, RF_SW=38). Przed pierwszym uruchomieniem potwierdź pinout, TCXO i tryb RF switch według dokumentacji **konkretnego kupionego kompletu**. Płytka wymaga anteny LoRa 868 MHz przed nadawaniem.

Radio: 868 MHz, BW 125 kHz, SF 7, CR 4/5, sync word 0x12, TX 10 dBm. Używaj tylko przy zgodności z lokalnymi ograniczeniami emisji (moc, duty-cycle). Wi-Fi i Bluetooth nie są tu potrzebne.

## Ograniczenia, których nie wolno przemilczeć na sprincie

1. **Timestamp TX** jest pobierany przed programowym `transmit()` i nie reprezentuje dokładnej chwili rozpoczęcia emisji RF.
2. **Timestamp RX** jest pobierany w przerwaniu DIO1 (RX_DONE), nadal nie jest to timestamp początku fali na antenie.
3. Długość pakietów to 32 bajty w obu kierunkach, aby zmniejszyć asymetrię czasu na antenie, ale nie usuwa to asymetrii opóźnień sterowników.
4. Synchronizacja jest **eksperymentalna**, nie ma potwierdzenia dokładności wystarczającej do TDOA; nawet offset może zawierać duży błąd systematyczny.
5. `esp_timer_get_time()` zeruje się po Deep Sleep — na tym etapie węzły pracują **bez deep sleep**; synchronizacja wymaga nowej sesji po restarcie.
6. DIO1 RX_DONE i serializacja protokołu są etapem PoC; brak uwierzytelnienia wiadomości, odporności na kolizje, automatycznej ponownej próby i bezpieczeństwa produkcyjnego.
7. Zdarzenia testowe nie są datami UTC; to mikrosekundy od startu, skorygowane do czasu centrali.
8. Nie używaj wyników do geolokalizacji rzeczywistych zdarzeń, dopóki błędy czasowe nie zostaną zmierzone na wspólnym impulsie testowym.

## Kryteria akceptacji kolejnych sprintów

- Sprint obecny: działający symulator i testy automatyczne; plan protokołu; pierwsza implementacja firmware.
- Po otrzymaniu 2 urządzeń: komunikaty SYNC w obie strony oraz logi offset/RTT, test utraty pakietów.
- Po otrzymaniu 4 urządzeń: badanie dryftu oraz wzajemnej zgodności zegarów (np. przez wspólny przewodowy impuls GPIO dla 2 urządzeń lub ten sam bodziec audio, uwzględniając opóźnienie toru pomiarowego). Pomiary co 5/30/300 s w różnych konfiguracjach.
- Po integracji audio: zbadaj definicję timestampu *próbki audio*, a nie czasu zakończenia klasyfikacji ML. Ciągły dźwięk piły wymaga korelacji wspólnych cech sygnału; samo `p(chainsaw)` nie wystarczy.

## Części zespołu
`chainsaw_detector/` Mateusza pozostaje bez zmian. Ten moduł ma dostarczać `SYNC`, później `EVENT` do centralnego ESP32. Komunikację centralnego ESP32 z backendem wdroży zespół po uzgodnieniu formatu danych.
