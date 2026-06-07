"""
Server Storage di TRIAGE — Event Bus 2.

Raccoglie e persiste gli eventi clinici:
  triage.started, triage.completed, triage.revealed,
  inference.completed, explainability.completed,
  feedback.submitted, review.submitted

I dati vengono riversati nell'Audit Log tramite query della facade.
"""

import json, logging, uuid
from typing import Optional
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from .database import connect, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.server_storage")

CLINICAL_EVENT_TYPES = {
    "triage.started", "triage.completed", "triage.revealed",
    "inference.completed", "explainability.completed",
    "feedback.submitted", "review.submitted",
}

app = FastAPI(
    title="TRIAGE — Server Storage (Event Bus 2)",
    description=(
        "Persistenza degli **eventi clinici** (Event Bus 2).\n\n"
        "Riceve eventi relativi al percorso diagnostico e li archivia su SQLite.\n\n"
        f"Tipi attesi: `{'`, `'.join(sorted(CLINICAL_EVENT_TYPES))}`"
    ),
    version="0.1.0",
)

@app.on_event("startup")
def startup(): init_db()


class ClinicalEvent(BaseModel):
    service:    str
    event_type: str = Field(description=f"Tipo evento. Attesi: {', '.join(sorted(CLINICAL_EVENT_TYPES))}")
    payload:    dict = Field(default_factory=dict)
    actor:      Optional[str] = "system"


@app.get("/health")
def health() -> dict:
    try:
        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM clinical_events").fetchone()[0]
        return {"status": "ok", "service": "server-storage", "events_stored": count}
    except Exception:
        return {"status": "ok", "service": "server-storage"}


@app.post("/events", status_code=201, summary="Registra un evento clinico")
def record_event(event: ClinicalEvent) -> dict:
    event_id = str(uuid.uuid4())
    with connect() as conn:
        conn.execute(
            "INSERT INTO clinical_events (event_id,service,event_type,payload,actor) VALUES (?,?,?,?,?)",
            (event_id, event.service, event.event_type, json.dumps(event.payload), event.actor)
        )
    logger.info("[ServerStorage] %s — %s", event.service, event.event_type)
    return {"event_id": event_id, "stored": True}


@app.get("/events", summary="Consulta eventi clinici")
def get_events(
    service:    Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    limit:      int           = Query(default=100, ge=1, le=1000),
) -> dict:
    with connect() as conn:
        q = "SELECT * FROM clinical_events WHERE 1=1"
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
