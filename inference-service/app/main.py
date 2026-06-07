"""Inference Service di TRIAGE."""

import io
import json
import logging
import os

import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image

from .model_loader import Predictor, load_model
from .schemas import ClinicalData, HealthResponse, PredictionResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.inference")

LABEL_NAMES    = {0: "assenza_tumore", 1: "presenza_tumore"}
AUDIT_LOG_URL  = os.environ.get("AUDIT_LOG_URL", "http://audit-log:8000")

tags_metadata = [
    {"name": "diagnostica", "description": "Classificazione binaria di immagini MRI cerebrali."},
    {"name": "sistema",     "description": "Probe di liveness e readiness del servizio."},
]

app = FastAPI(
    title="TRIAGE — Inference Service",
    description=(
        "Microservizio di **classificazione binaria** (presenza/assenza tumore) "
        "a partire da un'immagine MRI 2D in scala di grigi e da dati clinici tabulari.\n\n"
        "**Confini di responsabilità** — questo servizio *non* gestisce:\n"
        "- logica di triage → *Triage Orchestrator*\n"
        "- mappe di salienza / GradCAM → *Explainability Service*\n"
        "- persistenza dei feedback → *Feedback Service*\n"
        "- versionamento dei pesi → *Model Registry*"
    ),
    version="0.1.0",
    openapi_tags=tags_metadata,
)

_model: Predictor = load_model()


def _emit_event(event_type: str, payload: dict):
    """Emette un evento all'Audit Log in background. Non bloccante."""
    try:
        import httpx as _h
        _h.post(f"{AUDIT_LOG_URL}/audit/events", json={
            "service":    "inference-service",
            "event_type": event_type,
            "payload":    payload,
            "actor":      "system",
        }, timeout=3.0)
    except Exception:
        pass


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["sistema"],
    summary="Liveness / readiness probe",
)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model_loaded=_model is not None,
        model_version=_model.version,
        is_stub=_model.is_stub,
    )


def _decode_grayscale(raw: bytes) -> np.ndarray:
    try:
        img = Image.open(io.BytesIO(raw)).convert("L")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Immagine non valida: {exc}")
    return np.asarray(img)


@app.post(
    "/predict",
    response_model=PredictionResponse,
    tags=["diagnostica"],
    summary="Classificazione binaria MRI + dati clinici",
    responses={422: {"description": "Input non valido"}},
)
async def predict(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(..., description="Immagine MRI 2D (PNG/JPEG/TIFF)"),
    clinical_data: str = Form(default="{}"),
) -> PredictionResponse:
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=422, detail="File immagine vuoto.")

    arr = _decode_grayscale(raw)

    try:
        clinical = ClinicalData(**json.loads(clinical_data))
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"clinical_data JSON non valido: {exc}")

    label, confidence = _model.predict(arr, clinical.model_dump())
    logger.info("Predizione: label=%s confidence=%.4f", label, confidence)

    background_tasks.add_task(_emit_event, "inference.completed", {
        "label":         label,
        "confidence":    float(confidence),
        "model_version": _model.version,
        "is_stub":       _model.is_stub,
    })

    return PredictionResponse(
        label=label,
        label_name=LABEL_NAMES[label],
        confidence=confidence,
        model_version=_model.version,
        is_stub=_model.is_stub,
    )
