"""
Explainability Service (stub) di TRIAGE.

Responsabilità: produrre una spiegazione visiva (saliency map) per una
predizione già effettuata dall'Inference Service.

STUB — il metodo reale (es. GradCAM) non è ancora implementato.
Lo stub restituisce una heatmap casuale delle stesse dimensioni dell'immagine
in ingresso, nel formato esatto che userebbe GradCAM. Quando il metodo reale
sarà scelto, si sostituisce solo explain_stub() senza modificare il contratto.

NOTA ARCHITETTURALE
-------------------
L'orchestrator chiama prima l'Inference Service e poi questo servizio,
passando il label predetto affinché la spiegazione si riferisca alla classe
corretta. In futuro si può parallelizzare se l'Explainability Service carica
una propria copia del modello; per ora la sequenzialità è la scelta più
semplice e corretta.
"""

import base64
import io
import logging
import os

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.explainability")

tags_metadata = [
    {"name": "spiegabilità", "description": "Generazione di spiegazioni visive per le predizioni."},
    {"name": "sistema", "description": "Probe di liveness del servizio."},
]

app = FastAPI(
    title="TRIAGE — Explainability Service (stub)",
    description=(
        "Microservizio di spiegabilità: produce una **saliency map** "
        "per la classe predetta dall'Inference Service.\n\n"
        "> **Stub**: restituisce una heatmap casuale nel formato corretto. "
        "Implementare qui GradCAM o altro metodo post-hoc."
    ),
    version="0.1.0",
    openapi_tags=tags_metadata,
)


def explain_stub(image_arr: np.ndarray, label: int) -> np.ndarray:
    """
    Segnaposto deterministico per la saliency map.

    Genera una heatmap casuale (scala di grigi) delle stesse dimensioni
    dell'immagine in ingresso. In produzione questo metodo viene sostituito
    da GradCAM o da un altro approccio post-hoc — il contratto (ndarray 2D,
    stesse dimensioni dell'input) rimane invariato.
    """
    rng = np.random.default_rng(seed=label)
    return (rng.random(image_arr.shape[:2]) * 255).astype(np.uint8)


def encode_png(arr: np.ndarray) -> str:
    """Codifica un array 2D in una stringa base64 PNG."""
    buf = io.BytesIO()
    Image.fromarray(arr, mode="L").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@app.get("/health", tags=["sistema"], summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "service": "explainability-service", "is_stub": True}


@app.post(
    "/explain",
    tags=["spiegabilità"],
    summary="Genera la saliency map per una predizione",
    response_description="Heatmap base64 + metadati",
    responses={422: {"description": "Immagine non valida o label fuori range"}},
)
async def explain(
    image: UploadFile = File(..., description="Immagine MRI 2D originale (PNG/JPEG)"),
    label: int = Form(..., description="Label predetta dall'Inference Service (0 o 1)"),
    model_version: str = Form(default="unknown"),
) -> dict:
    """
    Genera una spiegazione visiva per la classe predetta.

    Riceve l'immagine MRI originale e il label prodotto dall'Inference
    Service, restituisce una saliency map codificata in base64 (PNG
    in scala di grigi, stesse dimensioni dell'input).

    Il campo `is_stub: true` indica che la mappa è generata dal
    segnaposto e non ha valore diagnostico.
    """
    if label not in (0, 1):
        raise HTTPException(status_code=422, detail="label deve essere 0 o 1")

    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=422, detail="File immagine vuoto.")
    try:
        img_arr = np.asarray(Image.open(io.BytesIO(raw)).convert("L"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Immagine non valida: {exc}")

    heatmap = explain_stub(img_arr, label)
    logger.info("Spiegazione generata: label=%s shape=%s", label, heatmap.shape)

    return {
        "explanation_type": "gradcam_stub",
        "saliency_map_b64": encode_png(heatmap),
        "width": int(heatmap.shape[1]),
        "height": int(heatmap.shape[0]),
        "label_explained": label,
        "model_version": model_version,
        "is_stub": True,
        "note": "Heatmap casuale — implementare GradCAM o metodo post-hoc equivalente.",
    }
