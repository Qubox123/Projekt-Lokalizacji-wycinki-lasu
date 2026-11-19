# Testy bez sprzętu — rozszerzenie sprintu

## Nowy rezultat: testowanie logiki synchronizacji w C++

W `firmware/include/sync_math.h` wydzielono obliczenia z `main.cpp`.
Tego kodu używa firmware ESP32, ale można go testować na zwykłym komputerze.

W katalogu `communication/`:

```bash
g++ -std=c++17 -Wall -Wextra -Werror \
    -Ifirmware/include firmware/tests_native/test_sync_math.cpp \
    -o /tmp/iot_sync_math_test
/tmp/iot_sync_math_test
```

Oczekiwany komunikat: `PASS: 3 native C++ sync-math tests`.

## Eksperyment utraty synchronizacji

```bash
python3 simulator/loss_experiment.py \
    --duration 300 --trials 30 \
    --intervals 10,30,60 --loss-rates 0,0.1,0.3 \
    --csv results/sync_loss.csv

python3 -m unittest discover -s tests -v
```

Powinno być 9 testów Pythona: 4 wcześniej istniejące i 5 nowych.

**Przedstawiaj wyniki jako symulację.**
`p95_abs_error_us` to percentyl błędu czasu skorygowanego względem
idealnego czasu centrali, nie wynik pomiaru urządzeń SX1262.
Eksperyment nie ocenia regulacyjnych ograniczeń duty-cycle ani prawdziwych
opóźnień sprzętowych. Krótkie interwały służą tylko porównaniu w modelu.
