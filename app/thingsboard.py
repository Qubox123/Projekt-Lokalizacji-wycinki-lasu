import logging

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Event, EventStatus

logger = logging.getLogger("lokalizator")


def build_payload(event: Event) -> dict:
    return {
        "ts": event.start_us // 1000,
        "values": {
            "latitude": round(event.lat, 6),
            "longitude": round(event.lon, 6),
            "radius": event.accuracy_m,       # promień niepewności [m]
            "event_id": event.id,
            "nodes": len(event.packets),      # ile węzłów usłyszało cięcie
        },
    }


def send_pending(db: Session) -> int:
    """Wysyła zlokalizowane zdarzenia, których jeszcze nie wysłano. Zwraca, ile wysłano.
    Jeśli ThingsBoard nie odpowiada, zdarzenie zostaje niewysłane i pętla spróbuje ponownie."""
    if not config.TB_TOKEN:
        return 0
    url = f"{config.TB_HOST}/api/v1/{config.TB_TOKEN}/telemetry"

    events = db.scalars(
        select(Event)
        .where(Event.status == EventStatus.LOCALIZED)
        .where(Event.tb_sent.is_(False))
        .order_by(Event.id)
    ).all()

    sent = 0
    for event in events:
        try:
            r = requests.post(url, json=build_payload(event), timeout=10)
        except requests.RequestException as e:
            logger.warning("ThingsBoard nieosiągalny (%s), spróbuję później", e)
            break
        if r.status_code == 200:
            event.tb_sent = True
            sent += 1
        else:
            logger.warning("ThingsBoard odrzucił zdarzenie %s: %s %s", event.id, r.status_code, r.text)
            break
    return sent