"""
ML-based seniority prediction.
Loads the live pipeline via the artifact registry (never hardcodes a filename).
"""
from apps.intelligence.ml_registry import get_pipeline

_VALID = {"junior", "senior", "senior_plus"}


def predict_seniority(title: str, description: str) -> str:
    """Return a seniority label for a single job. Never raises."""
    try:
        label = get_pipeline().predict([f"{title} {description}"])[0]
        return label if label in _VALID else "not_stated"
    except Exception:
        return "not_stated"
