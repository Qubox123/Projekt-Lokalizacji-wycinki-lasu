
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Sample = Annotated[int, Field(ge=0, le=255)]

UnixMicros = Annotated[int, Field(gt=1_577_836_800_000_000, lt=4_000_000_000_000_000)]

NodeId = Annotated[str, Field(min_length=1, max_length=32)]


class PacketIn(BaseModel):
    node_id: NodeId
    window_start_us: UnixMicros
    sample_rate_hz: Annotated[float, Field(gt=0, le=1000)]
    envelope: Annotated[list[Sample], Field(min_length=1, max_length=2000)]
    rssi: float | None = None
    snr: float | None = None


class NodeIn(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    alt_m: float | None = None
    active: bool = True


class NodeOut(NodeIn):
    model_config = ConfigDict(from_attributes=True)
    node_id: str


class PacketSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    node_id: str
    window_start_us: int
    window_end_us: int
    sample_rate_hz: float
    n_samples: int
    event_id: int | None
    received_at: datetime