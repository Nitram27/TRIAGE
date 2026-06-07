# TRIAGE — Inference Service

Microservizio del **layer applicativo** responsabile della **classificazione
binaria** (presenza/assenza tumore) a partire da un'immagine MRI 2D in scala di
grigi e dai relativi dati clinici tabulari. Restituisce `label` e `confidence`.

> **Stato attuale:** scheletro funzionante con **predittore-stub**. Non esiste
> ancora un modello addestrato: lo stub produce un output deterministico e
> **privo di valore diagnostico**, marcato da `is_stub: true` in ogni risposta.
> Serve a rendere il container eseguibile e testabile mentre il modello viene
> sviluppato.

## Confini di responsabilità (coerenti con l'architettura)

Questo servizio **non** si occupa di:

- **triage** → demandato al *Triage Orchestrator*;
- **spiegazioni / mappe di salienza** → demandate all'*Explainability Service*;
- **persistenza dei feedback** → demandata al *Feedback Service*;
- **versionamento dei pesi** → demandato al *Model Registry*.

## Struttura

```
inference-service/
├── app/
│   ├── main.py          # app FastAPI: endpoint /health e /predict
│   ├── model_loader.py  # interfaccia Predictor + StubPredictor + load_model()
│   └── schemas.py       # contratto dati (Pydantic)
├── Dockerfile
├── requirements.txt
└── .dockerignore
```

## Build ed esecuzione

```bash
docker build -t triage/inference-service:0.1.0 .
docker run --rm -p 8000:8000 triage/inference-service:0.1.0
```

Quando esisterà un modello reale, montarlo e indicarne il percorso:

```bash
docker run --rm -p 8000:8000 \
  -e MODEL_PATH=/models/triage.pt \
  -v /percorso/locale/ai/pesi:/models:ro \
  triage/inference-service:0.1.0
```

## Contratto API

### `GET /health`
```json
{"status":"ok","model_loaded":true,"model_version":"stub-0.1.0","is_stub":true}
```

### `POST /predict`  (multipart/form-data)

| Campo           | Tipo   | Descrizione                                  |
|-----------------|--------|----------------------------------------------|
| `image`         | file   | Immagine MRI 2D (PNG/JPEG/...)               |
| `clinical_data` | string | Dati clinici tabulari in JSON                |

Risposta:
```json
{"label":1,"label_name":"presenza_tumore","confidence":0.83,
 "model_version":"stub-0.1.0","is_stub":true}
```

Esempio:
```bash
curl -X POST http://localhost:8000/predict \
  -F "image=@mri.png" \
  -F 'clinical_data={"patient_id":"P001","age":54,"sex":"F","features":{}}'
```

## Inserire il modello reale

1. Implementare una classe `Predictor` (es. `TorchPredictor`) in `model_loader.py`.
2. Abilitarne il caricamento dentro `load_model()` quando `MODEL_PATH` è valido.
3. Aggiungere il framework (es. `torch`) a `requirements.txt`.

Nessun'altra parte del servizio va modificata: il contratto `/predict` resta
invariato.

## Note sul contratto clinico

Lo schema dei campi clinici tabulari è **volutamente generico** (`features`
aperto + anagrafici opzionali) finché lo schema definitivo non sarà fissato
nel documento di analisi dei requisiti.
