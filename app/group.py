"""Grupowanie pakietów w zdarzenia"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Event, EventStatus, Node, Packet


def assign_to_event(db: Session, packet: Packet) -> Event:
    """Dopisuje pakiet do pasującego otwartego zdarzenia albo zakłada nowe."""
    start = packet.window_start_us
    end = packet.window_end_us

    candidates = db.scalars(
        select(Event)
        .where(Event.status == EventStatus.OPEN)
        .where(Event.start_us <= end + config.MAX_GAP_US)
        .where(Event.end_us >= start - config.MAX_GAP_US)
        .order_by(Event.start_us)
    ).all()

    event = None
    for candidate in candidates:
        if packet.node_id not in candidate.node_ids:
            event = candidate
            break

    if event is None:
        event = Event(start_us=start, end_us=end, status=EventStatus.OPEN)
        db.add(event)
    else:
        event.start_us = min(event.start_us, start)
        event.end_us = max(event.end_us, end)

    packet.event = event
    return event


def update_status(db: Session, event: Event) -> None:
    """Kiedy zdarzenie ma pakiety od wszystkich aktywnych węzłów dostaje status ready"""
    if event.status != EventStatus.OPEN:
        return
    active_nodes = set(db.scalars(select(Node.node_id).where(Node.active)).all())
    have = event.node_ids
    if len(have) >= config.MIN_NODES and active_nodes <= have:
        _mark_ready(event)


def close_stale_events(db: Session) -> int:
    """Zamyka zdarzenia, które czekają dłużej niż EVENT_TIMEOUT_S. Zwraca, ile zamknięto.    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=config.EVENT_TIMEOUT_S)
    stale = db.scalars(
        select(Event)
        .where(Event.status == EventStatus.OPEN)
        .where(Event.created_at < cutoff)
    ).all()
    for event in stale:
        if len(event.node_ids) >= config.MIN_NODES:
            _mark_ready(event)
        else:
            event.status = EventStatus.INCOMPLETE
    return len(stale)


def _mark_ready(event: Event) -> None:
    event.status = EventStatus.READY
    # TODO (algorytm lokalizacji)