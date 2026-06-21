# Inference Service di TRIAGE
# Immagine base snella; quando si aggiungera' un framework ML (PyTorch /
# TensorFlow) andra' valutata un'immagine con runtime CUDA se serve la GPU.
FROM python:3.11-slim

# Buone pratiche: niente .pyc, output non bufferizzato.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Installo prima le dipendenze (sfrutta la cache dei layer Docker).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copio il codice applicativo.
COPY app/ ./app/

# Utente non-root (sicurezza).
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Healthcheck a livello container, allineato all'endpoint /health.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
