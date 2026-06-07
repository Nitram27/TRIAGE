import os
"""
Audit Log di TRIAGE — Facade di aggregazione.

NON persiste dati direttamente. Instrada gli eventi in ingresso verso
il servizio corretto e aggrega le query dai due sottosistemi:

  Event Bus 1 → System Log    (eventi tecnici di sistema)
  Event Bus 2 → Server Storage (eventi clinici)
            ↘ ↙
           Audit Log  ← facade che unifica la vista
"""

import logging, os
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.audit_log")

SYSTEM_LOG_URL     = os.environ.get("SYSTEM_LOG_URL",     "http://system-log:8000")
SERVER_STORAGE_URL = os.environ.get("SERVER_STORAGE_URL", "http://server-storage:8000")

# Tipi che vanno al System Log (Event Bus 1)
SYSTEM_EVENT_TYPES = {
    "service.started", "service.stopped", "service.error", "service.healthcheck",
    "model.promoted", "model.rollback", "ingestion.completed", "ingestion.failed",
}
# Tutto il resto va al Server Storage (Event Bus 2)

app = FastAPI(
    title="TRIAGE — Audit Log (Facade)",
    description=(
        "Facade di aggregazione su **System Log** e **Server Storage**.\n\n"
        "**Routing in ingresso**:\n"
        "- eventi tecnici (`service.*`, `model.*`, `ingestion.*`) → System Log\n"
        "- eventi clinici (`triage.*`, `inference.*`, `feedback.*`) → Server Storage\n\n"
        "**Aggregazione in uscita**: `GET /audit/events` unifica i risultati di entrambi."
    ),
    version="0.2.0",
)


class AuditEvent(BaseModel):
    service:    str
    event_type: str
    payload:    dict = Field(default_factory=dict)
    actor:      Optional[str] = "system"


@app.get("/health", summary="Liveness probe + stato dei sottosistemi")
async def health() -> dict:
    sub = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in [("system-log", SYSTEM_LOG_URL),
                           ("server-storage", SERVER_STORAGE_URL)]:
            try:
                r = await client.get(f"{url}/health")
                sub[name] = r.json()
            except Exception as exc:
                sub[name] = {"reachable": False, "error": str(exc)}
    return {
        "status":     "ok",
        "service":    "audit-log",
        "role":       "facade",
        "subsystems": sub,
    }


@app.post("/audit/events", status_code=201, summary="Riceve un evento e lo instrada")
async def record_event(event: AuditEvent) -> dict:
    """
    Instrada l'evento al sottosistema corretto:
    - tipi di sistema → System Log (Event Bus 1)
    - tipi clinici    → Server Storage (Event Bus 2)
    """
    if event.event_type in SYSTEM_EVENT_TYPES:
        target_url = f"{SYSTEM_LOG_URL}/events"
        bus        = "event-bus-1 → system-log"
    else:
        target_url = f"{SERVER_STORAGE_URL}/events"
        bus        = "event-bus-2 → server-storage"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(target_url, json=event.model_dump())
        result = r.json()
    except Exception as exc:
        raise HTTPException(503, f"Impossibile inviare l'evento a {bus}: {exc}")

    logger.info("Evento instradato → %s: %s", bus, event.event_type)
    return {**result, "routed_to": bus}


@app.get("/audit/events", summary="Vista aggregata di tutti gli eventi (System Log + Server Storage)")
async def get_events(
    service:    Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    limit:      int           = Query(default=100, ge=1, le=500),
) -> dict:
    """
    Aggrega gli eventi da System Log e Server Storage,
    li ordina per timestamp e restituisce la vista unificata.
    """
    params = {}
    if service:    params["service"]    = service
    if event_type: params["event_type"] = event_type
    params["limit"] = limit

    system_events   = []
    clinical_events = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{SYSTEM_LOG_URL}/events",     params=params)
            system_events = r.json().get("events", [])
        except Exception as exc:
            logger.warning("System Log non raggiungibile: %s", exc)
        try:
            r = await client.get(f"{SERVER_STORAGE_URL}/events", params=params)
            clinical_events = r.json().get("events", [])
        except Exception as exc:
            logger.warning("Server Storage non raggiungibile: %s", exc)

    # Aggiungo il tag della sorgente per chiarezza
    for e in system_events:   e["source"] = "system-log"
    for e in clinical_events: e["source"] = "server-storage"

    all_events = sorted(
        system_events + clinical_events,
        key=lambda e: e.get("received_at", ""),
        reverse=True,
    )[:limit]

    return {
        "events":          all_events,
        "total":           len(all_events),
        "system_log":      len(system_events),
        "server_storage":  len(clinical_events),
    }
