import os
"""
Data Ingestion Service di TRIAGE.

Responsabilità:
  1. Validare l'immagine MRI in ingresso
  2. Pre-processarla (scala di grigi, resize 224×224 LANCZOS)
  3. Archiviarla nel DB SQLite (Image Store)
  4. Restituire l'immagine pre-processata all'API Gateway
"""

import base64
import io
import json
import logging
import uuid

import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image

from .database import connect, init_db

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
logger = logging.getLogger("triage.ingestion")

TARGET_SIZE = (224, 224)
MAX_FILE_MB = 20
MIN_DIM_PX  = 32

app = FastAPI(
    title="TRIAGE — Data Ingestion Service",
    description=(
        "Validazione, pre-processing e archiviazione delle immagini MRI.\n\n"
        "Ogni immagine viene salvata nel DB SQLite con il relativo `image_id`."
    ),
    version="0.2.0",
)


@app.on_event("startup")
def startup():
    init_db()
    logger.info("Image Store DB inizializzato.")


def _validate(raw: bytes) -> Image.Image:
    if not raw:
        raise HTTPException(422, "File immagine vuoto.")
    if len(raw) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(422, f"File troppo grande (max {MAX_FILE_MB}MB).")
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(422, f"Immagine non valida o corrotta: {exc}")
    w, h = img.size
    if w < MIN_DIM_PX or h < MIN_DIM_PX:
        raise HTTPException(422, f"Immagine troppo piccola: {w}×{h}px (min {MIN_DIM_PX}px).")
    return img


def _preprocess(img: Image.Image):
    orig_mode = img.mode
    orig_size = img.size
    img_gray  = img.convert("L")
    img_res   = img_gray.resize(TARGET_SIZE, Image.LANCZOS)
    report = {
        "original_mode": orig_mode,
        "original_size": list(orig_size),
        "output_size":   list(TARGET_SIZE),
        "checks": [
            "valid_image", "integrity_ok", "min_size_ok",
            "grayscale_converted" if orig_mode != "L" else "already_grayscale",
            f"resized_to_{TARGET_SIZE[0]}x{TARGET_SIZE[1]}_LANCZOS",
        ],
    }
    return img_res, report


def _encode_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@app.get("/health", summary="Liveness probe")
def health() -> dict:
    try:
        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM mri_images").fetchone()[0]
        return {"status": "ok", "service": "data-ingestion",
                "images_stored": count, "is_stub": False}
    except Exception:
        return {"status": "ok", "service": "data-ingestion"}


@app.post("/ingest", summary="Valida, pre-processa e archivia l'immagine MRI")
async def ingest(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    clinical_data: str = Form(default="{}"),
) -> dict:
    raw      = await image.read()
    img      = _validate(raw)
    img_proc, report = _preprocess(img)
    b64      = _encode_png(img_proc)
    image_id = str(uuid.uuid4())

    # Archiviazione nel DB (Image Store)
    with connect() as conn:
        conn.execute("""
            INSERT INTO mri_images
              (image_id, original_filename, original_mode, original_size, output_size, image_b64)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            image_id,
            image.filename,
            report["original_mode"],
            json.dumps(report["original_size"]),
            json.dumps(report["output_size"]),
            b64,
        ))

    logger.info("MRI archiviata: image_id=%s %s→%s",
                image_id, report["original_size"], TARGET_SIZE)

    background_tasks.add_task(_emit_event, "data-ingestion", "ingestion.completed",
        {"image_id": image_id, "filename": image.filename,
         "original_size": report["original_size"],
         "output_size": list(TARGET_SIZE)})

    return {
        "image_id":               image_id,
        "preprocessed_image_b64": b64,
        "original_filename":      image.filename,
        "validation":             {**report, "valid": True},
        "image_store_status":     "saved",
    }


@app.get("/images", summary="Lista immagini archiviate")
def list_images(limit: int = 50) -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT image_id, original_filename, original_size, output_size, submitted_at "
            "FROM mri_images ORDER BY submitted_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "images": [{
            "image_id":          r["image_id"],
            "original_filename": r["original_filename"],
            "original_size":     json.loads(r["original_size"]),
            "output_size":       json.loads(r["output_size"]),
            "submitted_at":      r["submitted_at"],
        } for r in rows],
        "total": len(rows),
    }


@app.get("/images/{image_id}", summary="Recupera un'immagine per image_id",
         responses={404: {"description": "Immagine non trovata"}})
def get_image(image_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM mri_images WHERE image_id=?", (image_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"image_id={image_id} non trovato.")
    return {
        "image_id":          row["image_id"],
        "original_filename": row["original_filename"],
        "original_size":     json.loads(row["original_size"]),
        "output_size":       json.loads(row["output_size"]),
        "image_b64":         row["image_b64"],
        "submitted_at":      row["submitted_at"],
    }
