import os
"""
Model Registry di TRIAGE.

Gestisce versioni del modello, promozioni, rollback e campioni
di training — tutti persistiti su SQLite.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .database import connect, init_db

AUDIT_LOG_URL = os.environ.get("AUDIT_LOG_URL", "http://audit-log:8000")


def _emit_event(event_type: str, payload: dict):
    try:
        import httpx as _h
        _h.post(f"{AUDIT_LOG_URL}/audit/events",
                json={"service": "model-registry", "event_type": event_type,
                      "payload": payload, "actor": "system"}, timeout=3.0)
    except Exception:
        pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.model_registry")

tags_metadata = [
    {"name": "modelli",    "description": "Catalogo e gestione versioni del modello."},
    {"name": "retraining", "description": "Campioni etichettati per il retraining."},
    {"name": "sistema",    "description": "Probe di liveness."},
]

app = FastAPI(
    title="TRIAGE — Model Registry",
    description=(
        "Catalogo versioni modello + raccolta campioni etichettati.\n\n"
        "Tutti i dati sono persistiti su **SQLite** (volume Docker)."
    ),
    version="0.3.0",
    openapi_tags=tags_metadata,
)


@app.on_event("startup")
def startup():
    init_db()
    logger.info("Model Registry DB inizializzato.")


# ── Schemi ────────────────────────────────────────────────────────────────────

class PromoteRequest(BaseModel):
    promoted_by: Optional[str] = "system"


class TrainingSample(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "case_id": "abc-123", "final_label": 1,
        "confidence_override": 0.85, "clinician_id": "medico_01",
        "agreed_with_ai": False,
    }})
    case_id:             str
    final_label:         int   = Field(ge=0, le=1)
    confidence_override: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    clinician_id:        Optional[str]   = None
    agreed_with_ai:      bool            = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_model(row) -> dict:
    return {
        "version":      row["version"],
        "status":       row["status"],
        "framework":    row["framework"],
        "architecture": row["architecture"],
        "dataset":      row["dataset"],
        "weights_path": row["weights_path"],
        "metrics":      json.loads(row["metrics_json"] or "{}"),
        "is_stub":      bool(row["is_stub"]),
        "created_at":   row["created_at"],
    }


# ── Sistema ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["sistema"])
def health() -> dict:
    try:
        with connect() as conn:
            current = conn.execute(
                "SELECT version FROM models WHERE status='production'"
            ).fetchone()
            n_models   = conn.execute("SELECT COUNT(*) FROM models").fetchone()[0]
            n_samples  = conn.execute("SELECT COUNT(*) FROM training_samples").fetchone()[0]
        return {
            "status":           "ok",
            "service":          "model-registry",
            "current_version":  current["version"] if current else None,
            "total_versions":   n_models,
            "training_samples": n_samples,
            "is_stub":          True,
        }
    except Exception:
        return {"status": "ok", "service": "model-registry"}


# ── Modelli ───────────────────────────────────────────────────────────────────

@app.get("/models", tags=["modelli"], summary="Lista tutte le versioni")
def list_models() -> dict:
    with connect() as conn:
        rows    = conn.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()
        current = conn.execute(
            "SELECT version FROM models WHERE status='production'"
        ).fetchone()
    return {
        "versions":        [_row_to_model(r) for r in rows],
        "current_version": current["version"] if current else None,
        "total":           len(rows),
    }


@app.get("/models/current", tags=["modelli"], summary="Versione in produzione")
def get_current() -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM models WHERE status='production'"
        ).fetchone()
    if not row:
        raise HTTPException(404, "Nessun modello in produzione.")
    return {**_row_to_model(row), "current": True}


@app.get("/models/{version}", tags=["modelli"],
         responses={404: {"description": "Versione non trovata"}})
def get_model(version: str) -> dict:
    with connect() as conn:
        row     = conn.execute("SELECT * FROM models WHERE version=?", (version,)).fetchone()
        current = conn.execute(
            "SELECT version FROM models WHERE status='production'"
        ).fetchone()
    if not row:
        raise HTTPException(404, f"Versione '{version}' non trovata.")
    return {**_row_to_model(row),
            "current": current and current["version"] == version}


@app.post("/models/{version}/promote", tags=["modelli"], summary="Promuove a produzione",
          responses={404: {"description": "Versione non trovata"}})
def promote(version: str, body: PromoteRequest) -> dict:
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM models WHERE version=?", (version,)).fetchone():
            raise HTTPException(404, f"Versione '{version}' non trovata.")
        conn.execute("UPDATE models SET status='retired' WHERE status='production'")
        conn.execute("UPDATE models SET status='production' WHERE version=?", (version,))
        conn.execute(
            "INSERT INTO promotions (version, promoted_by) VALUES (?, ?)",
            (version, body.promoted_by)
        )
    logger.info("Promozione: %s → production (by %s)", version, body.promoted_by)
    _emit_event("model.promoted", {"version": version, "promoted_by": body.promoted_by})
    return {"message": f"Versione '{version}' promossa a produzione.",
            "version": version, "promoted_by": body.promoted_by,
            "promoted_at": datetime.utcnow().isoformat()}


@app.post("/models/rollback", tags=["modelli"], summary="Rollback alla versione precedente",
          responses={400: {"description": "Nessuna versione precedente"}})
def rollback() -> dict:
    with connect() as conn:
        history = conn.execute(
            "SELECT version FROM promotions ORDER BY promoted_at DESC LIMIT 2"
        ).fetchall()
        if len(history) < 2:
            raise HTTPException(400, "Nessuna versione precedente per il rollback.")
        previous = history[1]["version"]
        conn.execute("UPDATE models SET status='retired' WHERE status='production'")
        conn.execute("UPDATE models SET status='production' WHERE version=?", (previous,))
    logger.info("Rollback → %s", previous)
    _emit_event("model.rollback", {"from": "previous", "to": previous})
    return {"message": f"Rollback completato → versione '{previous}' in produzione."}


@app.get("/models/history/promotions", tags=["modelli"], summary="Storia promozioni")
def promotion_history() -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM promotions ORDER BY promoted_at DESC"
        ).fetchall()
    return {"history": [dict(r) for r in rows]}


# ── Training ──────────────────────────────────────────────────────────────────

@app.post("/training-data", tags=["retraining"],
          summary="Registra campione etichettato per il retraining",
          status_code=201)
def add_training_sample(body: TrainingSample) -> dict:
    with connect() as conn:
        conn.execute("""
            INSERT INTO training_samples
              (case_id, final_label, confidence_override, clinician_id, agreed_with_ai)
            VALUES (?, ?, ?, ?, ?)
        """, (body.case_id, body.final_label, body.confidence_override,
              body.clinician_id, int(body.agreed_with_ai)))
        total = conn.execute("SELECT COUNT(*) FROM training_samples").fetchone()[0]
    logger.info("Campione registrato: case_id=%s label=%s", body.case_id, body.final_label)
    return {"message": "Campione registrato per il retraining.",
            "case_id": body.case_id, "queue_size": total}


@app.get("/training-data", tags=["retraining"], summary="Lista campioni di training")
def list_training_data(limit: int = 50) -> dict:
    with connect() as conn:
        rows    = conn.execute(
            "SELECT * FROM training_samples ORDER BY received_at DESC LIMIT ?", (limit,)
        ).fetchall()
        pending = conn.execute(
            "SELECT COUNT(*) FROM training_samples WHERE used_for_training=0"
        ).fetchone()[0]
        total   = conn.execute("SELECT COUNT(*) FROM training_samples").fetchone()[0]
    return {
        "samples":       [dict(r) for r in rows],
        "total":         total,
        "pending_train": pending,
    }
