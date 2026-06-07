# TRIAGE

## Credenziali di accesso

| Ruolo | Username | Password | Pannello |
|---|---|---|---|
| Radiologo | `radiologo` | `radiologo123` | Carica MRI, sottomette casi alla coda |
| Medico | `medico` | `medico123` | Revisiona casi, conferma o corregge l'AI |
| Tecnico | `tecnico` | `tecnico123` | Monitoraggio operativo: log, servizi, modello |

---

## Avvio rapido

**Prima esecuzione** (o dopo modifiche ai file):
```bash
docker compose down -v
docker compose build --no-cache
docker compose up
```

**Avvii successivi** (senza modifiche):
```bash
docker compose up
```

- **UI** → http://localhost:7860
- **API Gateway (Swagger)** → http://localhost:8080/docs

Al primo avvio Docker scarica le immagini base e installa le dipendenze (~5-10 minuti).

---

## Flusso clinico

### Pannello Radiologo
1. Carica immagine MRI + dati paziente (ID, età, sesso — obbligatori)
2. Clicca **"Sottometti caso"**
3. Il sistema valida e pre-processa la MRI (224×224, scala di grigi), esegue la classificazione AI e calcola la priorità di triage
4. Il caso entra nella coda di revisione medica

### Pannello Medico
1. Clicca **"Carica casi in coda"** — i casi appaiono ordinati per confidence crescente (i più incerti prima)
2. Seleziona un caso e clicca **"Apri caso selezionato"**
3. Appaiono subito: immagine MRI, dati paziente, classificazione AI, confidence, priorità triage, saliency map
4. Il medico sceglie la **decisione finale** (label) e può modificare la **confidence score**
5. Aggiunge note cliniche e clicca **"Invia revisione"**
6. La revisione viene persistita su SQLite; il Model Registry viene notificato del nuovo campione etichettato; l'Audit Log riceve l'evento

### Pannello Tecnico
- **Stato microservizi**: caricato automaticamente al login, aggiornabile manualmente
- **Modello in produzione**: versione attiva, dropdown per selezionare e promuovere una versione precedente (rollback)
- **Log eventi**: aggregazione da System Log (eventi tecnici) e Server Storage (eventi clinici), filtrabile per tipo
- **Campioni per retraining**: lista dei casi revisionati dal medico disponibili per addestrare il modello

---

## Priorità di triage

La priorità è calcolata dalla confidence del modello con logica inversa:

| Confidence | Priorità | Significato |
|---|---|---|
| < 60% | 🔴 Alta | Modello molto incerto → revisione urgente |
| 60% – 85% | 🟡 Media | Incertezza moderata |
| ≥ 85% | 🟢 Bassa | Modello sicuro |

I casi sono ordinati in coda dalla confidence più bassa alla più alta.

---

## Servizi

| Servizio | Porta | Stato | Descrizione |
|---|---|---|---|
| frontend | 7860 | ✅ | Gradio — 3 pannelli: radiologo, medico, tecnico |
| api-gateway | 8080 | ✅ | Auth HTTP Basic, validazione contratto REST, routing |
| data-ingestion | 8000 | ✅ | Validazione MRI + resize 224×224 LANCZOS + SQLite |
| triage-orchestrator | 8000 | ✅ stub | Inference + Explainability + calcolo priorità triage |
| inference-service | 8000 | ✅ stub | Classificazione binaria (StubPredictor) |
| explainability-service | 8000 | ✅ stub | Saliency map placeholder (interfaccia GradCAM-ready) |
| feedback-service | 8000 | ✅ | Coda casi + revisioni mediche, SQLite persistente |
| model-registry | 8000 | ✅ stub | Versionamento modelli + campioni retraining, SQLite |
| audit-log | 8000 | ✅ | Facade: instrada eventi a System Log e Server Storage |
| system-log | 8000 | ✅ | Persiste eventi tecnici (Event Bus 1), SQLite |
| server-storage | 8000 | ✅ | Persiste eventi clinici (Event Bus 2), SQLite |

---

## Architettura Event Bus

```
Microservizi → Audit Log (facade)
                 ↙              ↘
          System Log        Server Storage
       (eventi tecnici)    (eventi clinici)
           SQLite               SQLite
```

**Event Bus 1 → System Log**: `service.*`, `model.*`, `ingestion.*`
**Event Bus 2 → Server Storage**: `triage.*`, `inference.*`, `feedback.*`

---

## Database SQLite persistenti

| Servizio | Volume Docker | Contenuto |
|---|---|---|
| data-ingestion | `mri-data` | Immagini MRI pre-processate + metadati |
| feedback-service | `feedback-data` | Casi clinici in coda + revisioni mediche |
| model-registry | `registry-data` | Versioni modello + promozioni + campioni retraining |
| system-log | `system-log-data` | Eventi tecnici di sistema |
| server-storage | `server-storage-data` | Eventi clinici del percorso diagnostico |

---

## Struttura

```
triage/
├── docker-compose.yml
├── requirements.txt
├── frontend/                   # Gradio — 3 ruoli
├── api-gateway/                # FastAPI — auth + routing + validazione
├── data-ingestion/             # FastAPI + SQLite — preprocessing MRI
├── triage-orchestrator/        # FastAPI stub — coordinamento diagnostico
├── inference-service/          # FastAPI stub — classificazione binaria
├── explainability-service/     # FastAPI stub — saliency map
├── feedback-service/           # FastAPI + SQLite — coda casi + HITL
├── model-registry/             # FastAPI + SQLite — versionamento modelli
├── audit-log/                  # FastAPI — facade Event Bus
├── system-log/                 # FastAPI + SQLite — Event Bus 1
└── server-storage/             # FastAPI + SQLite — Event Bus 2
```

---

## Validazione contratto REST (API Gateway)

Ogni richiesta `POST /api/v1/triage` viene validata prima di essere inoltrata:

| Campo | Controllo |
|---|---|
| `image` | Presente, non vuoto, Content-Type accettato (PNG/JPEG/TIFF/BMP) |
| `clinical_data` | Oggetto JSON valido |

---
