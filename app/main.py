from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Node, Packet
from .schemas import NodeIn, NodeOut, PacketIn, PacketSummary

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Lokalizator wycinki: backend")

DB = Annotated[Session, Depends(get_db)]


@app.get("/health")
def health():
    return {"status": "ok"}


# Węzły

@app.put("/nodes/{node_id}", response_model=NodeOut)
def insert_node(node_id: Annotated[str, Path(min_length=1, max_length=32)], data: NodeIn, db: DB):
    """Rejestruje węzeł"""
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





    db.commit()
    return {"status": "ok", "packet_id": row.id, "samples": row.n_samples}


@app.get("/packets", response_model=list[PacketSummary])
def list_packets(db: DB, limit: Annotated[int, Query(ge=1, le=500)] = 20):
    return db.scalars(select(Packet).order_by(Packet.id.desc()).limit(limit)).all()