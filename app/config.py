import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lokalizator.db")

# TODO: tu dodać ustawienia grupowania, np.
#   MIN_NODES       - minimalna liczba węzłów w zdarzeniu (3),
#   MAX_GAP_US      - tolerancja nakładania się okien [µs],
#   EVENT_TIMEOUT_S - ile czekać na brakujące węzły [s].