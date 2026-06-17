"""
Feedback Service di TRIAGE.

Dopo ogni revisione medica:
  1. Salva la revisione nel DB (sincrono)
  2. Notifica il Model Registry — nuovo campione etichettato (background)
  3. Emette evento all'Audit Log (background)
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .database import connect, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.feedback")

MODEL_REGISTRY_URL = os.environ.get("MODEL_REGISTRY_URL", "http://model-registry:8000")
AUDIT_LOG_URL      = os.environ.get("AUDIT_LOG_URL",      "http://audit-log:8000")

app = FastAPI(
    title="TRIAGE — Feedback Service",
    description=(
        "Coda casi clinici e raccolta revisioni mediche (HITL).\n\n"
        "Dopo ogni revisione notifica:\n"
        "- **Model Registry** → nuovo campione etichettato per retraining\n"
        "- **Audit Log** → evento di tracciabilità"
    ),
    version="0.3.0",
)


@app.on_event("startup")
def startup():
    init_db()


# ── Background tasks ──────────────────────────────────────────────────────────

def _notify_model_registry(case_id: str, final_label: int,
                            confidence_override: Optional[float],
                            clinician_id: str, agreed: bool):
    """Notifica il Model Registry del nuovo campione etichettato."""
    try:
        httpx.post(
            f"{MODEL_REGISTRY_URL}/training-data",
            json={
                "case_id":             case_id,
                "final_label":         final_label,
                "confidence_override": confidence_override,
                "clinician_id":        clinician_id,
                "agreed_with_ai":      agreed,
            },
            timeout=5.0,
        )
        logger.info("Model Registry notificato: case_id=%s", case_id)
    except Exception as exc:
        logger.warning("Notifica Model Registry fallita: %s", exc)


def _emit_audit_event(case_id: str, clinician_id: str, agreed: bool,
                      label_override: Optional[int]):
    """Emette un evento di audit per tracciabilità."""
    try:
        httpx.post(
            f"{AUDIT_LOG_URL}/audit/events",
            json={
                "service":    "feedback-service",
                "event_type": "feedback.submitted",
                "payload": {
                    "case_id":        case_id,
                    "clinician_id":   clinician_id,
                    "agreed":         agreed,
                    "label_override": label_override,
                },
                "actor": clinician_id,
            },
            timeout=5.0,
        )
        logger.info("Audit Log notificato: case_id=%s", case_id)
    except Exception as exc:
        logger.warning("Notifica Audit Log fallita: %s", exc)


# ── Schemi ────────────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    case_id:          str
    patient_id:       Optional[str] = None
    age:              Optional[int] = None
    sex:              Optional[str] = None
    image_b64:        str
    inference_json:   str
    explanation_json: str
    triage_json:      str
    submitted_by:     Optional[str] = None


class ReviewCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "clinician_id": "medico_01", "agreed": False,
        "label_override": 0, "confidence_override": 0.75,
        "notes": "Immagine di scarsa qualità, riclassificata."
    }})
    clinician_id:        str
    agreed:              bool
    label_override:      Optional[int]   = Field(default=None, ge=0, le=1)
    confidence_override: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notes:               Optional[str]   = None


class FeedbackCreate(BaseModel):
    case_id:        str
    clinician_id:   str
    agreed:         bool
    label_override: Optional[int] = None
    notes:          Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    try:
        with connect() as conn:
            total   = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM cases WHERE status='pending_review'"
            ).fetchone()[0]
        return {"status": "ok", "service": "feedback-service",
                "cases_total": total, "cases_in_queue": pending}
    except Exception:
        return {"status": "ok", "service": "feedback-service"}


@app.post("/cases", status_code=201)
def create_case(body: CaseCreate) -> dict:
    try:
        confidence = json.loads(body.inference_json).get("confidence", 0.5)
    except Exception:
        confidence = 0.5
    with connect() as conn:
        try:
            conn.execute("""
                INSERT INTO cases
                  (case_id, patient_id, age, sex, image_b64,
                   inference_json, explanation_json, triage_json,
                   confidence, submitted_by)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (body.case_id, body.patient_id, body.age, body.sex,
                  body.image_b64, body.inference_json, body.explanation_json,
                  body.triage_json, confidence, body.submitted_by))
        except Exception as exc:
            raise HTTPException(409, f"case_id già presente: {exc}")
    logger.info("Caso creato: %s confidence=%.4f (by %s)",
                body.case_id, confidence, body.submitted_by)
    return {"case_id": body.case_id, "status": "pending_review"}


@app.get("/cases")
def list_cases(status: Optional[str] = None) -> dict:
    with connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT case_id,patient_id,age,sex,triage_json,confidence,"
                "status,submitted_by,submitted_at,review_json,reviewed_at,inference_json"
                " FROM cases WHERE status=? "
                "ORDER BY confidence ASC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT case_id,patient_id,age,sex,triage_json,confidence,"
                "status,submitted_by,submitted_at,review_json,reviewed_at,inference_json"
                " FROM cases "
                "ORDER BY confidence ASC"
            ).fetchall()
    cases = [{
        "case_id":      r["case_id"],
        "patient_id":   r["patient_id"],
        "age":          r["age"],
        "sex":          r["sex"],
        "triage":       json.loads(r["triage_json"]),
        "confidence":   r["confidence"],
        "status":       r["status"],
        "submitted_by": r["submitted_by"],
        "submitted_at": r["submitted_at"],
        "reviewed_at":  r["reviewed_at"],
        "review":       json.loads(r["review_json"]) if r["review_json"] else None,
        "inference":    json.loads(r["inference_json"]) if r["inference_json"] else {},
    } for r in rows]
    return {"cases": cases, "total": len(cases)}


@app.get("/cases/{case_id}")
def get_case(case_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Caso {case_id} non trovato.")
    return {
        "case_id":      row["case_id"],
        "patient_id":   row["patient_id"],
        "age":          row["age"],
        "sex":          row["sex"],
        "image_b64":    row["image_b64"],
        "inference":    json.loads(row["inference_json"]),
        "explanation":  json.loads(row["explanation_json"]),
        "triage":       json.loads(row["triage_json"]),
        "status":       row["status"],
        "submitted_by": row["submitted_by"],
        "submitted_at": row["submitted_at"],
        "review":       json.loads(row["review_json"]) if row["review_json"] else None,
    }


@app.post("/cases/{case_id}/review")
def review_case(case_id: str, body: ReviewCreate,
                background_tasks: BackgroundTasks) -> dict:
    """
    Salva la revisione medica, poi in background:
      → notifica Model Registry (nuovo campione per retraining)
      → emette evento all'Audit Log
    """
    with connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Caso {case_id} non trovato.")
        if not body.agreed and body.label_override is None:
            raise HTTPException(422, "label_override obbligatorio quando agreed=false.")

        # Calcola il label finale
        if body.agreed:
            inf = json.loads(row["inference_json"])
            final_label = inf.get("label", 0)
        else:
            final_label = body.label_override

        review = {
            "clinician_id":        body.clinician_id,
            "agreed":              body.agreed,
            "label_override":      body.label_override,
            "confidence_override": body.confidence_override,
            "final_label":         final_label,
            "notes":               body.notes,
            "reviewed_at":         datetime.utcnow().isoformat(),
        }
        conn.execute("""
            UPDATE cases SET status='reviewed', reviewed_by=?, reviewed_at=?, review_json=?
            WHERE case_id=?
        """, (body.clinician_id, review["reviewed_at"], json.dumps(review), case_id))

    logger.info("Revisione: case_id=%s agreed=%s label_finale=%s",
                case_id, body.agreed, final_label)

    # Background: notifica Model Registry e Audit Log
    background_tasks.add_task(
        _notify_model_registry,
        case_id, final_label, body.confidence_override,
        body.clinician_id, body.agreed,
    )
    background_tasks.add_task(
        _emit_audit_event,
        case_id, body.clinician_id, body.agreed, body.label_override,
    )

    return {"case_id": case_id, "status": "reviewed", "review": review}


@app.post("/feedback")
def create_feedback(body: FeedbackCreate) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO feedback (case_id,clinician_id,agreed,label_override,notes) VALUES (?,?,?,?,?)",
            (body.case_id, body.clinician_id, int(body.agreed), body.label_override, body.notes),
        )
        row = conn.execute("SELECT * FROM feedback WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)
