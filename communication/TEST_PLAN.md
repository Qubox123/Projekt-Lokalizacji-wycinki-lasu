
# Metodyka testowania synchronizacji LoRa

## Cel
Ocena poprawności wymiany znaczników czasu oraz
dokładności synchronizacji trzech węzłów pomiarowych
względem węzła centralnego.

## Konfiguracja
- 3 x ESP32-S3 + SX1262: sensory
- 1 x ESP32-S3 + SX1262: centrala
- LoRa: 868 MHz, BW 125 kHz, SF7 (konfiguracja wstępna)

## Etap 1: Test komunikacji
1. Uruchomienie centrali i jednego sensora.
2. Wysłanie pakietu SYNC_REQ.
3. Odebranie pakietu SYNC_REPLY.
4. Weryfikacja identyfikatorów i numeru sekwencyjnego.
5. Powtórzenie testu dla pozostałych sensorów.

## Etap 2: Estymacja offsetu
Rejestrujemy cztery znaczniki czasu:
- t1: nadanie żądania przez sensor
- t2: odbiór żądania przez centralę
- t3: nadanie odpowiedzi przez centralę
- t4: odbiór odpowiedzi przez sensor

Estymator:
offset = ((t2 - t1) + (t3 - t4)) / 2

RTT = (t4 - t1) - (t3 - t2)

## Etap 3: Pomiary
- Przeprowadzenie serii wymian synchronizacyjnych.
- Rejestracja offsetu, RTT i utraconych ramek.
- Zbadanie wpływu odstępu między synchronizacjami.
- Porównanie wyników dla jednego i trzech sensorów.

## Etap 4: Weryfikacja dokładności
- Podanie wspólnego sygnału referencyjnego do dwóch ESP32.
- Zarejestrowanie timestampów tego samego zdarzenia.
- Obliczenie różnicy czasów po zastosowaniu korekty.
- Wyznaczenie średniego i maksymalnego błędu.
- Ocena przydatności otrzymanej dokładności do TDOA.

## Ograniczenia
- Symulacja nie zastępuje pomiarów radiowych.
- Timestampy programowe mogą zawierać opóźnienia.
- Asymetria opóźnień powoduje błąd estymacji offsetu.
- Dokładność wymagana dla TDOA nie została jeszcze potwierdzona.
