"""
ML-based seniority prediction.
Loads the live pipeline lazily on first use via the artifact registry.
"""
from __future__ import annotations
import numpy as np
from apps.intelligence.ml_registry import get_pipeline, live_version

_VALID = {"junior", "senior", "senior_plus"}


def predict_seniority(title: str, description: str) -> str:
    """Single-job convenience wrapper. Never raises."""
    try:
        label = get_pipeline().predict([f"{title} {description}"])[0]
        return label if label in _VALID else "not_stated"
    except Exception:
        return "not_stated"


def predict_batch(texts: list[str]) -> list[dict]:
    """
    Predict seniority for a list of pre-concatenated texts.

    Returns a list of dicts:
        {"label": str, "confidence": float, "model_version": str}
    """
    pipe = get_pipeline()
    version = live_version()
    labels = pipe.predict(texts)
    probas = pipe.predict_proba(texts)
    return [
        {
            "label":         lbl if lbl in _VALID else "not_stated",
            "confidence":    round(float(np.max(p)), 4),
            "model_version": version,
        }
        for lbl, p in zip(labels, probas)
    ]
