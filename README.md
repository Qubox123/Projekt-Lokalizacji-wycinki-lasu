# Projekt lokalizacji wycinki lasu

Węzły w lesie nasłuchują dźwięku piły mechanicznej i zgłaszają wykrycia przez LoRa
do serwera, który lokalizuje źródło.

| Katalog | Zawartość |
|---|---|
| [`chainsaw_detector/`](chainsaw_detector/README.md) | trening i eksport modelu wykrywającego piłę |
| [`esp32/`](esp32/README.md) | kod węzła (Pycom LoPy 1.0), testy sprzętu, narzędzia |
| [`docs/`](docs/) | [sprzęt](docs/hardware.md), [firmware](docs/flashing.md) |
