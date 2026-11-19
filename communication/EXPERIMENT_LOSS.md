# Eksperyment: utracone odpowiedzi i dryft zegarów (bez elektroniki)

## Cel
Rozszerzenie istniejącego symulatora dwukierunkowej synchronizacji o:
- utratę odpowiedzi `SYNC_REPLY` (symulowaną jako Bernoulli),
- używanie **ostatniej zaakceptowanej korekty offsetu**,
- zmianę błędu pomiędzy kolejnymi udanymi synchronizacjami,
- porównanie różnych okresów synchronizacji,
- zapis statystyk do CSV.

## Uruchomienie

Z katalogu `communication/`:

```bash
python3 simulator/loss_experiment.py --duration 300 --trials 30 \
    --intervals 10,30,60 --loss-rates 0,0.1,0.3 \
    --csv results/sync_loss.csv

python3 -m unittest discover -s tests -v
```

Kolumny CSV:
- `interval_s` – planowany okres ponawiania synchronizacji,
- `loss_rate` – zadane prawdopodobieństwo utraty odpowiedzi,
- `reception_pct` – udział odebranych odpowiedzi,
- `p95_abs_error_us` – 95. percentyl wartości bezwzględnej błędu,
- `max_abs_error_us` – największy błąd bezwzględny,
- `max_correction_age_s` – maksymalny wiek ostatniego użytego offsetu,
- `unsynchronized_seconds` – liczba kroków bez uzyskanej synchronizacji.

## Założenia i ograniczenia
- Wszystkie wartości są SYMULOWANE; nie są pomiarami SX1262.
- Zakładamy liniowe dryfty zegarów w ppm, jak w dotychczasowym `Clock`.
- Odpowiedź jest dostarczona lub całkowicie utracona; brak retransmisji.
- Estymator offsetu ten sam co w `clock_sync.py`.
- Aktualizacja offsetu zachodzi po poprawnym `SYNC_REPLY`; pomiędzy
  synchronizacjami korekta jest stała (brak estymacji dryftu).
- Symulacja nie odwzorowuje kolizji radiowych, czasu zajętości kanału,
  duty-cycle, sleep/wake ani wszystkich opóźnień sterownika.
- Nie należy uznawać okresów 10/30/60 s za dopuszczalne w eterze:
  docelowy harmonogram musi uwzględniać czas emisji pakietów oraz lokalne
  ograniczenia regulacyjne i współdzielenie kanału.

## Pytanie inżynierskie na sprint
Jak zmienia się błąd zegara, gdy odpowiedzi synchronizacyjne giną, a sensor
przez dłuższy czas korzysta z ostatniego offsetu?

Następny krok po dostawie:
zastąpić założone parametry jittera i opóźnień pomiarami rzeczywistymi,
a błąd synchronizacji weryfikować niezależnym wspólnym impulsem testowym.
