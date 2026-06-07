"""
Caricamento e astrazione del modello.

Definisce un'interfaccia `Predictor` indipendente dal framework (PyTorch,
TensorFlow/Keras, ...). Finche' non esiste un modello addestrato, viene usato
`StubPredictor`, che produce un output deterministico e chiaramente marcato
come NON clinico. Quando i pesi saranno disponibili (versionati dal Model
Registry), bastera' implementare una nuova classe `Predictor` e modificare
`load_model()` senza toccare il resto del servizio.
"""

from __future__ import annotations

import hashlib
import logging
import os
from abc import ABC, abstractmethod
from typing import Tuple

import numpy as np

logger = logging.getLogger("triage.inference")


class Predictor(ABC):
    """Interfaccia comune a qualunque modello di inferenza."""

    version: str = "unknown"
    is_stub: bool = True

    @abstractmethod
    def predict(self, image: np.ndarray, tabular: dict) -> Tuple[int, float]:
        """Restituisce (label_binaria, confidence in [0,1])."""
        raise NotImplementedError


class StubPredictor(Predictor):
    """
    Predittore segnaposto deterministico.

    Genera label e confidence in modo riproducibile a partire dall'hash
    dell'input, cosi' lo stesso input da' sempre lo stesso risultato (utile
    per i test di integrazione). NON ha alcun valore diagnostico.
    """

    version = "stub-0.1.0"
    is_stub = True

    def predict(self, image: np.ndarray, tabular: dict) -> Tuple[int, float]:
        seed_material = image.tobytes()[:1024] + repr(sorted(tabular.items())).encode()
        digest = hashlib.sha256(seed_material).digest()
        # Mappo l'hash in una pseudo-probabilita' stabile in [0,1].
        prob = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
        label = int(prob >= 0.5)
        confidence = prob if label == 1 else 1.0 - prob
        return label, round(float(confidence), 4)


def load_model() -> Predictor:
    """
    Punto unico di caricamento del modello.

    Legge MODEL_PATH dall'ambiente. Se non e' valorizzato o il file non
    esiste, ricade sullo stub. Qui andra' inserito il caricamento dei pesi
    reali (es. torch.load / keras.models.load_model) quando disponibili.
    """
    model_path = os.environ.get("MODEL_PATH", "").strip()

    if model_path and os.path.exists(model_path):
        # TODO: implementare il caricamento del modello reale, es.:
        #   return TorchPredictor(model_path)
        logger.warning(
            "MODEL_PATH=%s presente ma nessun loader reale e' ancora "
            "implementato: uso lo stub.",
            model_path,
        )

    logger.warning(
        "Nessun modello reale caricato: attivo StubPredictor (output NON clinico)."
    )
    return StubPredictor()
