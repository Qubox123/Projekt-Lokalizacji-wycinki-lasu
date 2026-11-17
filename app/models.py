from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventStatus:
    """Możliwe stany zdarzenia"""
    OPEN = "open"
    READY = "ready"
    INCOMPLETE = "incomplete"
    LOCALIZED = "localized"
    FAILED = "failed"


class Node(Base):
    """Węzeł pomiarowy w lesie. Rejestrujemy go przy montażu."""
    __tablename__ = "nodes"

    node_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    lat: Mapped[float]                 # szerokość geograficzna
    lon: Mapped[float]                 # długość geograficzna
    alt_m: Mapped[float | None]        # wysokość [m]
    active: Mapped[bool] = mapped_column(default=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_us: Mapped[int] = mapped_column(BigInteger, index=True)
    end_us: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(16), default=EventStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lat: Mapped[float | None]
    lon: Mapped[float | None]
    accuracy_m: Mapped[float | None]

    packets: Mapped[list["Packet"]] = relationship(back_populates="event")

    @property
    def node_ids(self) -> set[str]:
        """Zbiór węzłów, które już przysłały pakiet do tego zdarzenia."""
        return {p.node_id for p in self.packets}


class Packet(Base):
    __tablename__ = "packets"
    __table_args__ = (UniqueConstraint("node_id", "window_start_us", name="uq_node_window"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id"), index=True)
    window_start_us: Mapped[int] = mapped_column(BigInteger, index=True)
    sample_rate_hz: Mapped[float]
    envelope: Mapped[list[int]] = mapped_column(JSON)
    rssi: Mapped[float | None]
    snr: Mapped[float | None]
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), index=True)
    event: Mapped[Event | None] = relationship(back_populates="packets")

    @property
    def n_samples(self) -> int:
        return len(self.envelope)

    @property
    def window_end_us(self) -> int:
        return self.window_start_us + round(self.n_samples / self.sample_rate_hz * 1_000_000)