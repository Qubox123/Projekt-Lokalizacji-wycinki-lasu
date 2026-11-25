import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lokalizator.db")

# Ile węzłów musi usłyszeć zdarzenie, żeby dało się policzyć pozycję
MIN_NODES = 3

# Tolerancja przy łączeniu okien w jedno zdarzenie [µs].
MAX_GAP_US = 1_500_000

# Ile sekund czekamy na pakiety od brakujących węzłów, zanim zamkniemy zdarzenie.
EVENT_TIMEOUT_S = 120

CLEANUP_INTERVAL_S = 10

SPEED_OF_SOUND = 343.0
# Ile metrów poza węzły szukamy źródła. Obszar szukania = prostokąt wokół węzłów
# poszerzony o tę wartość.
SEARCH_MARGIN_M = 200.0
# Krok siatki przy szukaniu punktu startowego [m].
GRID_STEP_M = 5.0
MIN_CORRELATION = 0.3
# dopuszczalna różnica czasu między parą węzłów [s]
# (fizycznie różnica nie może przekroczyć odległość / prędkość dźwięku).
TDOA_MARGIN_S = 0.05
# Zakładana niepewność wyznaczenia różnicy czasu [s]. Z niej liczymy promień błędu.
TDOA_SIGMA_S = 0.01
HUBER_SCALE_M = 10.0
AMBIGUITY_DIST_M = 50.0

TB_HOST = os.getenv("TB_HOST", "https://eu.thingsboard.cloud")
TB_TOKEN = os.getenv("TB_TOKEN")