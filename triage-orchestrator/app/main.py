"""
Triage Orchestrator (stub) di TRIAGE.

Flusso single-step: riceve immagine + dati clinici, invoca Inference
e Explainability, calcola la priorità di triage, restituisce il risultato
completo al gateway che lo salva nella coda casi.

L'automation bias prevention è ora gestita a livello di presentazione:
il Pannello Medico del frontend non mostra il risultato AI finché il medico
non ha espresso la propria valutazione indipendente.
"""

import logging
import os
import uuid

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile

AUDIT_LOG_URL = os.environ.get("AUDIT_LOG_URL", "http://audit-log:8000")


def _emit_event(service: str, event_type: str, payload: dict, actor: str = "system"):
    try:
        import httpx as _h
        _h.post(f"{AUDIT_LOG_URL}/audit/events",
                json={"service": service, "event_type": event_type,
                      "payload": payload, "actor": actor}, timeout=3.0)
    except Exception:
        pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.triage")

INFERENCE_URL      = os.environ.get("INFERENCE_SERVICE_URL",      "http://inference-service:8000")
EXPLAINABILITY_URL = os.environ.get("EXPLAINABILITY_SERVICE_URL", "http://explainability-service:8000")

SOGLIA_ALTA  = 0.60
SOGLIA_MEDIA = 0.85

app = FastAPI(
    title="TRIAGE — Triage Orchestrator (stub)",
    description=(
        "Coordinamento diagnostico single-step.\n\n"
        "Chiama Inference Service + Explainability Service e restituisce "
        "il risultato completo al gateway, che lo archivia nella coda casi.\n\n"
        "**Logica di triage inversa** *(scelta di progetto)*: "
        "confidence bassa → priorità alta."
    ),
    version="0.3.0",
)


def _calcola_priorita(confidence: float) -> dict:
    if confidence < SOGLIA_ALTA:
        return {"priority": "alta",  "reason": "incertezza elevata del modello"}
    if confidence < SOGLIA_MEDIA:
        return {"priority": "media", "reason": "incertezza moderata del modello"}
    return     {"priority": "bassa", "reason": "predizione ad alta confidence"}


@app.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "service": "triage-orchestrator", "is_stub": True}


@app.post("/triage", summary="Esegue inference + explainability + triage")
async def triage(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    clinical_data: str = Form(default="{}"),
) -> dict:
    raw     = await image.read()
    case_id = str(uuid.uuid4())

    # Inference
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r_inf = await client.post(
                f"{INFERENCE_URL}/predict",
                files={"image": (image.filename, raw, image.content_type)},
                data={"clinical_data": clinical_data},
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Inference Service irraggiungibile: {exc}")
    if r_inf.status_code != 200:
        raise HTTPException(r_inf.status_code, r_inf.text)
    inference = r_inf.json()

    # Explainability
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r_exp = await client.post(
                f"{EXPLAINABILITY_URL}/explain",
                files={"image": (image.filename, raw, image.content_type)},
                data={"label": str(inference["label"]), "model_version": inference["model_version"]},
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Explainability Service irraggiungibile: {exc}")
    if r_exp.status_code != 200:
        raise HTTPException(r_exp.status_code, r_exp.text)
    explanation = r_exp.json()

    triage_decision = _calcola_priorita(inference["confidence"])
    logger.info("Triage: case_id=%s confidence=%.4f priorità=%s",
                case_id, inference["confidence"], triage_decision["priority"])

    background_tasks.add_task(_emit_event, "triage-orchestrator", "triage.completed",
        {"case_id": case_id,
         "priority": triage_decision["priority"],
         "confidence": inference.get("confidence"),
         "label": inference.get("label")})

    return {
        "case_id":     case_id,
        "inference":   inference,
        "explanation": explanation,
        "triage":      triage_decision,
    }
