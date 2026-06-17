"""
API Gateway di TRIAGE.

Autenticazione HTTP Basic con tre ruoli:
  radiologo / radiologo123 → sottomette casi MRI alla coda
  medico    / medico123    → consulta la coda e invia revisioni cliniche
  tecnico   / tecnico123   → monitoraggio operativo (log, servizi, modello)

Flusso radiologo  POST /api/v1/triage:
  1. Valida contratto REST
  2. Data Ingestion (valida + preprocess)
  3. Triage Orchestrator (inference + explainability + triage)
  4. Salva caso nella coda (Feedback Service)
  5. Restituisce conferma al radiologo (case_id + priorità)

Flusso medico:
  GET  /api/v1/cases                    → lista coda
  GET  /api/v1/cases/{case_id}          → dettaglio caso
  POST /api/v1/cases/{case_id}/review   → invia revisione

Flusso tecnico (monitoraggio):
  GET  /api/v1/monitoring/status        → stato tutti i microservizi
  GET  /api/v1/monitoring/logs          → log aggregati (Audit Log)
  GET  /api/v1/monitoring/model         → modello in produzione
  GET  /api/v1/monitoring/models        → lista versioni
  POST /api/v1/monitoring/model/promote/{version} → promuove versione
  GET  /api/v1/monitoring/training-data → campioni per retraining
"""

import base64
import json
import logging
import os
import secrets

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("triage.gateway")

# ── URL servizi interni ───────────────────────────────────────────────────────
TRIAGE_URL         = os.environ.get("TRIAGE_ORCHESTRATOR_URL",    "http://triage-orchestrator:8000")
FEEDBACK_URL       = os.environ.get("FEEDBACK_SERVICE_URL",       "http://feedback-service:8000")
DATA_INGESTION_URL = os.environ.get("DATA_INGESTION_URL",         "http://data-ingestion:8000")
INFERENCE_URL      = os.environ.get("INFERENCE_SERVICE_URL",      "http://inference-service:8000")
EXPLAINABILITY_URL = os.environ.get("EXPLAINABILITY_SERVICE_URL", "http://explainability-service:8000")
MODEL_REGISTRY_URL = os.environ.get("MODEL_REGISTRY_URL",         "http://model-registry:8000")
AUDIT_LOG_URL      = os.environ.get("AUDIT_LOG_URL",              "http://audit-log:8000")
SYSTEM_LOG_URL     = os.environ.get("SYSTEM_LOG_URL",             "http://system-log:8000")
SERVER_STORAGE_URL = os.environ.get("SERVER_STORAGE_URL",         "http://server-storage:8000")

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/tiff", "image/bmp"}

# ── Autenticazione ────────────────────────────────────────────────────────────
security = HTTPBasic()

USERS = {
    "radiologo": {"password": "radiologo123", "role": "radiologo"},
    "medico":    {"password": "medico123",    "role": "medico"},
    "tecnico":   {"password": "tecnico123",   "role": "tecnico"},
}


def get_user(credentials: HTTPBasicCredentials = Depends(security)):
    user = USERS.get(credentials.username)
    ok = user and secrets.compare_digest(
        credentials.password.encode(), user["password"].encode()
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return {"username": credentials.username, "role": user["role"]}


def require_radiologo(user=Depends(get_user)):
    if user["role"] != "radiologo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accesso riservato al radiologo.")
    return user


def require_medico(user=Depends(get_user)):
    if user["role"] != "medico":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accesso riservato al medico.")
    return user


def require_tecnico(user=Depends(get_user)):
    if user["role"] != "tecnico":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accesso riservato al tecnico.")
    return user


# ── Validazione contratto REST ────────────────────────────────────────────────

def _validate_image(image: UploadFile, raw: bytes):
    if not raw:
        raise HTTPException(422, "Campo 'image': file vuoto.")
    ct = (image.content_type or "").lower().split(";")[0].strip()
    if ct and ct not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(422, f"Content-Type '{ct}' non accettato. "
                                 f"Consentiti: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}")


def _validate_clinical_data(clinical_data: str) -> dict:
    try:
        parsed = json.loads(clinical_data)
        if not isinstance(parsed, dict):
            raise ValueError("deve essere un oggetto JSON {}")
        return parsed
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"'clinical_data' JSON non valido: {exc}")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TRIAGE — API Gateway",
    description=(
        "Unico punto d'ingresso con **autenticazione HTTP Basic**.\n\n"
        "---\n\n"
        "**🩻 Radiologo** (`radiologo` / `radiologo123`)\n\n"
        "- `POST /api/v1/triage` — carica MRI + dati paziente, avvia il percorso diagnostico e inserisce il caso nella coda di revisione medica\n\n"
        "---\n\n"
        "**🏥 Medico** (`medico` / `medico123`)\n\n"
        "- `GET /api/v1/cases` — lista casi in coda (ordinati per confidence crescente)\n"
        "- `GET /api/v1/cases/{case_id}` — dettaglio caso con MRI, risultato AI e saliency map\n"
        "- `POST /api/v1/cases/{case_id}/review` — invia revisione clinica (conferma o corregge label e confidence)\n\n"
        "---\n\n"
        "**🔧 Tecnico** (`tecnico` / `tecnico123`)\n\n"
        "- `GET /api/v1/monitoring/status` — stato health di tutti i microservizi\n"
        "- `GET /api/v1/monitoring/logs` — log aggregati da System Log e Server Storage\n"
        "- `GET /api/v1/monitoring/model` — versione del modello in produzione\n"
        "- `GET /api/v1/monitoring/models` — lista di tutte le versioni disponibili\n"
        "- `POST /api/v1/monitoring/model/promote/{version}` — promuove una versione a produzione (rollback)\n"
        "- `GET /api/v1/monitoring/training-data` — campioni etichettati disponibili per il retraining\n"
    ),
    version="0.6.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.get("/api/v1/me", summary="Informazioni utente corrente")
def get_me(user=Depends(get_user)) -> dict:
    """Endpoint leggero per verificare le credenziali e ottenere il ruolo."""
    return {"username": user["username"], "role": user["role"]}


@app.get("/api/v1/status", summary="Stato aggregato servizi")
async def status_all(user=Depends(get_user)) -> dict:
    services = {
        "data-ingestion":         DATA_INGESTION_URL,
        "inference-service":      INFERENCE_URL,
        "explainability-service": EXPLAINABILITY_URL,
        "triage-orchestrator":    TRIAGE_URL,
        "feedback-service":       FEEDBACK_URL,
        "model-registry":         MODEL_REGISTRY_URL,
        "audit-log":              AUDIT_LOG_URL,
        "system-log":             SYSTEM_LOG_URL,
        "server-storage":         SERVER_STORAGE_URL,
    }
    result = {}
    async with httpx.AsyncClient(timeout=4.0) as client:
        for name, url in services.items():
            try:
                r = await client.get(f"{url}/health")
                result[name] = {"reachable": True, **r.json()}
            except Exception as exc:
                result[name] = {"reachable": False, "error": str(exc)}
    return result


# ── Flusso Tecnico ────────────────────────────────────────────────────────────

@app.post(
    "/api/v1/triage",
    summary="[Tecnico] Sottomette un caso MRI alla coda",
    responses={
        422: {"description": "Immagine o clinical_data non validi"},
        503: {"description": "Servizi interni non raggiungibili"},
    },
)
async def triage(
    image: UploadFile = File(...),
    clinical_data: str = Form(default="{}"),
    user=Depends(require_radiologo),
) -> dict:
    """
    Flusso completo tecnico:
    1. Valida contratto REST
    2. Data Ingestion → preprocess
    3. Triage Orchestrator → inference + spiegazione + triage
    4. Salva caso nella coda
    5. Restituisce conferma (case_id + priorità) — il risultato AI non viene trasmesso
    """
    raw = await image.read()
    _validate_image(image, raw)
    cd = _validate_clinical_data(clinical_data)

    # Data Ingestion
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r_ingest = await client.post(
                f"{DATA_INGESTION_URL}/ingest",
                files={"image": (image.filename, raw, image.content_type)},
                data={"clinical_data": clinical_data},
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Data Ingestion irraggiungibile: {exc}")
    if r_ingest.status_code != 200:
        raise HTTPException(r_ingest.status_code, r_ingest.text)

    ingestion    = r_ingest.json()
    preprocessed = base64.b64decode(ingestion["preprocessed_image_b64"])
    image_id     = ingestion["image_id"]
    cd["image_id"] = image_id

    # Triage Orchestrator
    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            r_triage = await client.post(
                f"{TRIAGE_URL}/triage",
                files={"image": ("preprocessed.png", preprocessed, "image/png")},
                data={"clinical_data": json.dumps(cd)},
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Triage Orchestrator irraggiungibile: {exc}")
    if r_triage.status_code != 200:
        raise HTTPException(r_triage.status_code, r_triage.text)

    result = r_triage.json()

    # Salva nella coda casi
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{FEEDBACK_URL}/cases", json={
                "case_id":          result["case_id"],
                "patient_id":       cd.get("patient_id"),
                "age":              cd.get("age"),
                "sex":              cd.get("sex"),
                "image_b64":        ingestion["preprocessed_image_b64"],
                "inference_json":   json.dumps(result["inference"]),
                "explanation_json": json.dumps(result["explanation"]),
                "triage_json":      json.dumps(result["triage"]),
                "submitted_by":     user["username"],
            })
    except Exception as exc:
        logger.warning("Salvataggio coda fallito: %s", exc)

    logger.info("Caso in coda: %s priorità=%s by=%s",
                result["case_id"], result["triage"]["priority"], user["username"])

    # Al tecnico torna solo la conferma — il risultato AI resta nel server
    return {
        "case_id":  result["case_id"],
        "triage":   result["triage"],
        "message":  "Caso elaborato e aggiunto alla coda di revisione medica.",
        "ingestion": {"image_id": image_id, "validation": ingestion["validation"]},
    }


# ── Flusso Medico ─────────────────────────────────────────────────────────────

@app.get("/api/v1/cases", summary="[Medico] Lista casi in coda")
async def list_cases(status: str = "pending_review", user=Depends(require_medico)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{FEEDBACK_URL}/cases", params={"status": status})
        return resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Feedback Service irraggiungibile: {exc}")


@app.get("/api/v1/cases/{case_id}", summary="[Medico] Dettaglio caso")
async def get_case(case_id: str, user=Depends(require_medico)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{FEEDBACK_URL}/cases/{case_id}")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.text)
        return resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Feedback Service irraggiungibile: {exc}")


@app.post("/api/v1/cases/{case_id}/review", summary="[Medico] Invia revisione")
async def review_case(case_id: str, request: Request, user=Depends(require_medico)) -> dict:
    body = await request.json()
    body["clinician_id"] = user["username"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{FEEDBACK_URL}/cases/{case_id}/review", json=body)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.text)
        return resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Feedback Service irraggiungibile: {exc}")


# ── Monitoraggio operativo (Tecnico) ──────────────────────────────────────────

@app.get("/api/v1/monitoring/status", summary="[Tecnico] Stato di tutti i microservizi")
async def monitoring_status(user=Depends(require_tecnico)) -> dict:
    services = {
        "data-ingestion":         DATA_INGESTION_URL,
        "inference-service":      INFERENCE_URL,
        "explainability-service": EXPLAINABILITY_URL,
        "triage-orchestrator":    TRIAGE_URL,
        "feedback-service":       FEEDBACK_URL,
        "model-registry":         MODEL_REGISTRY_URL,
        "audit-log":              AUDIT_LOG_URL,
        "system-log":             SYSTEM_LOG_URL,
        "server-storage":         SERVER_STORAGE_URL,
    }
    result = {}
    async with httpx.AsyncClient(timeout=4.0) as client:
        for name, url in services.items():
            try:
                r = await client.get(f"{url}/health")
                result[name] = {"reachable": True, **r.json()}
            except Exception as exc:
                result[name] = {"reachable": False, "error": str(exc)}
    return result


@app.get("/api/v1/monitoring/logs", summary="[Tecnico] Log aggregati")
async def monitoring_logs(
    service: str = None, event_type: str = None, limit: int = 100,
    user=Depends(require_tecnico),
) -> dict:
    params = {"limit": limit}
    if service:    params["service"]    = service
    if event_type: params["event_type"] = event_type
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{AUDIT_LOG_URL}/audit/events", params=params)
        return r.json()
    except Exception as exc:
        raise HTTPException(503, f"Audit Log non raggiungibile: {exc}")


@app.get("/api/v1/monitoring/model", summary="[Tecnico] Modello in produzione")
async def monitoring_model(user=Depends(require_tecnico)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{MODEL_REGISTRY_URL}/models/current")
        if r.status_code == 404:
            return {"message": "Nessun modello in produzione."}
        return r.json()
    except Exception as exc:
        raise HTTPException(503, f"Model Registry non raggiungibile: {exc}")


@app.get("/api/v1/monitoring/training-data", summary="[Tecnico] Campioni per retraining")
async def monitoring_training(user=Depends(require_tecnico)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{MODEL_REGISTRY_URL}/training-data")
        return r.json()
    except Exception as exc:
        raise HTTPException(503, f"Model Registry non raggiungibile: {exc}")


@app.post("/api/v1/monitoring/model/rollback", summary="[Tecnico] Rollback alla versione precedente")
async def monitoring_rollback(user=Depends(require_tecnico)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{MODEL_REGISTRY_URL}/models/rollback")
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text)
        return r.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Model Registry non raggiungibile: {exc}")


@app.get("/api/v1/monitoring/models", summary="[Tecnico] Lista tutte le versioni del modello")
async def monitoring_models(user=Depends(require_tecnico)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{MODEL_REGISTRY_URL}/models")
        return r.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Model Registry non raggiungibile: {exc}")


@app.post("/api/v1/monitoring/model/promote/{version}",
          summary="[Tecnico] Promuove una versione specifica a produzione")
async def monitoring_promote(version: str, user=Depends(require_tecnico)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{MODEL_REGISTRY_URL}/models/{version}/promote",
                json={"promoted_by": user["username"]},
            )
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text)
        return r.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Model Registry non raggiungibile: {exc}")
