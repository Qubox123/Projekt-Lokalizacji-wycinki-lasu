import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config
from .database import Base, SessionLocal, engine, get_db
from .group import assign_to_event, close_stale_events, update_status
from .models import Event, Node, Packet
from .schemas import EventOut, NodeIn, NodeOut, PacketIn, PacketSummary


logger = logging.getLogger("lokalizator")

Base.metadata.create_all(bind=engine)

def _cleanup_once() -> None:
    with SessionLocal() as db:
        if close_stale_events(db):
            db.commit()


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(config.CLEANUP_INTERVAL_S)
        try:
            await asyncio.to_thread(_cleanup_once)
        except Exception:
            logger.exception("Błąd przy zamykaniu starych zdarzeń")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()

app = FastAPI(title="Lokalizator wycinki: backend")

DB = Annotated[Session, Depends(get_db)]


@app.get("/health")
def health():
    return {"status": "ok"}


# Węzły

@app.put("/nodes/{node_id}", response_model=NodeOut)
def insert_update_node(node_id: Annotated[str, Path(min_length=1, max_length=32)], data: NodeIn, db: DB):
    """Rejestruje węzeł albo aktualizuje dane"""
    node = db.get(Node, node_id)
    if node is None:
        node = Node(node_id=node_id)
        db.add(node)
    for field, value in data.model_dump().items():
        setattr(node, field, value)
    db.commit()
    db.refresh(node)
    return node


@app.get("/nodes", response_model=list[NodeOut])
def list_nodes(db: DB):
    return db.scalars(select(Node).order_by(Node.node_id)).all()


# Pakiety

@app.post("/packets", status_code=201)
def receive_packet(packet: PacketIn, db: DB):
    if db.get(Node, packet.node_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Nieznany węzeł '{packet.node_id}'. Najpierw zarejestruj go przez PUT /nodes/{{node_id}}.",
        )

    row = Packet(**packet.model_dump())
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return JSONResponse(status_code=200, content={"status": "duplicate"})

    event = assign_to_event(db, row)
    update_status(db, event)

    db.commit()
    return {
        "status": "ok",
        "packet_id": row.id,
        "samples": row.n_samples,
        "event_id": event.id,
        "event_status": event.status,
    }


@app.get("/packets", response_model=list[PacketSummary])
def list_packets(db: DB, limit: Annotated[int, Query(ge=1, le=500)] = 20):
    return db.scalars(select(Packet).order_by(Packet.id.desc()).limit(limit)).all()

@app.get("/events", response_model=list[EventOut])
def list_events(db: DB, status: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 20):
    query = select(Event).order_by(Event.id.desc()).limit(limit)
    if status:
        query = query.where(Event.status == status)
    return db.scalars(query).all()


@app.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, db: DB):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego zdarzenia")
    return event