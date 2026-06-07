"""Schemi dei dati (contratto API) dell'Inference Service di TRIAGE."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ClinicalData(BaseModel):
    """Dati clinici tabulari associati all'immagine MRI."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "patient_id": "P001",
                "age": 54,
                "sex": "F",
                "features": {"sintomo_cefalea": 1, "durata_sintomi_gg": 30},
            }
        }
    )

    patient_id: Optional[str] = Field(
        default=None, description="Identificativo pseudonimizzato del paziente"
    )
    age: Optional[int] = Field(default=None, ge=0, le=120, description="Età in anni")
    sex: Optional[str] = Field(default=None, description="Sesso biologico (es. 'F', 'M')")
    # Campo aperto: contenitore per le feature cliniche tabulari finché
    # lo schema definitivo non viene fissato nell'analisi dei requisiti.
    features: dict = Field(
        default_factory=dict,
        description="Feature cliniche aggiuntive (schema da consolidare nei requisiti)",
    )


class PredictionResponse(BaseModel):
    """Esito della classificazione binaria."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "label": 1,
                "label_name": "presenza_tumore",
                "confidence": 0.90,
                "model_version": "stub-0.1.0",
                "is_stub": True,
            }
        }
    )

    label: int = Field(description="Classe predetta: 0 = assenza tumore, 1 = presenza tumore")
    label_name: str = Field(description="Nome leggibile della classe predetta")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Probabilità associata alla classe predetta (in [0,1])",
    )
    model_version: str = Field(description="Versione del modello che ha prodotto la predizione")
    is_stub: bool = Field(
        description="True se la predizione proviene dal predittore-stub (nessun valore diagnostico)"
    )


class HealthResponse(BaseModel):
    """Stato di salute del servizio."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "model_loaded": True,
                "model_version": "stub-0.1.0",
                "is_stub": True,
            }
        }
    )

    status: str
    model_loaded: bool
    model_version: str
    is_stub: bool
