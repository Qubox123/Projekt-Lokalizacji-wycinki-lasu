import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lokalizator.db")

# Ile węzłów musi usłyszeć zdarzenie, żeby dało się policzyć pozycję
MIN_NODES = 3

# Tolerancja przy łączeniu okien w jedno zdarzenie [µs].
MAX_GAP_US = 1_500_000

# Ile sekund czekamy na pakiety od brakujących węzłów, zanim zamkniemy zdarzenie.
EVENT_TIMEOUT_S = 120

CLEANUP_INTERVAL_S = 10