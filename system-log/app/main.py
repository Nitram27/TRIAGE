"""
System Log di TRIAGE — Event Bus 1.

Raccoglie e persiste gli eventi di sistema (tecnici):
  service.started, service.stopped, service.error, service.healthcheck,
  model.promoted, model.rollback, ingestion.completed, ingestion.failed

I dati vengono riversati nell'Audit Log tramite query della facade.
"""

import json, logging, uuid
from typing import Optional
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from .database import connect, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.system_log")

SYSTEM_EVENT_TYPES = {
    "service.started", "service.stopped", "service.error", "service.healthcheck",
    "model.promoted", "model.rollback", "ingestion.completed", "ingestion.failed",
}

app = FastAPI(
    title="TRIAGE — System Log (Event Bus 1)",
    description=(
        "Persistenza degli **eventi di sistema** (Event Bus 1).\n\n"
        "Riceve eventi tecnici dai microservizi e li archivia su SQLite.\n\n"
        f"Tipi attesi: `{'`, `'.join(sorted(SYSTEM_EVENT_TYPES))}`"
    ),
    version="0.1.0",
)

@app.on_event("startup")
def startup(): init_db()


class SystemEvent(BaseModel):
    service:    str
    event_type: str = Field(description=f"Tipo evento. Attesi: {', '.join(sorted(SYSTEM_EVENT_TYPES))}")
    payload:    dict = Field(default_factory=dict)
    actor:      Optional[str] = "system"


@app.get("/health")
def health() -> dict:
    try:
        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM system_events").fetchone()[0]
        return {"status": "ok", "service": "system-log", "events_stored": count}
    except Exception:
        return {"status": "ok", "service": "system-log"}


@app.post("/events", status_code=201, summary="Registra un evento di sistema")
def record_event(event: SystemEvent) -> dict:
    event_id = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            "INSERT INTO system_events (event_id,service,event_type,payload,actor) VALUES (?,?,?,?,?)",
            (event_id, event.service, event.event_type, json.dumps(event.payload), event.actor)
        )
    logger.info("[SystemLog] %s — %s", event.service, event.event_type)
    return {"event_id": event_id, "stored": True}


@app.get("/events", summary="Consulta eventi di sistema")
def get_events(
    service:    Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    limit:      int           = Query(default=100, ge=1, le=1000),
) -> dict:
    with connect() as conn:
        q = "SELECT * FROM system_events WHERE 1=1"
        params = []
        if service:    q += " AND service=?";    params.append(service)
        if event_type: q += " AND event_type=?"; params.append(event_type)
        q += " ORDER BY received_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
    events = [{"event_id": r["event_id"], "service": r["service"],
               "event_type": r["event_type"], "payload": json.loads(r["payload"]),
               "actor": r["actor"], "received_at": r["received_at"]} for r in rows]
    return {"events": events, "total": len(events)}
