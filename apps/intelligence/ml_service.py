"""
ML-based seniority prediction.
Loads the trained TF-IDF + LR pipeline once per process (module-level cache).
"""
import pathlib
import joblib

_MODEL_PATH = pathlib.Path(__file__).parent / 'ml' / 'seniority_classifier.joblib'
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = joblib.load(_MODEL_PATH)
    return _pipeline


# Maps merged training labels back to the Job.seniority values used in the DB
_LABEL_MAP = {
    'junior':      'junior',
    'senior':      'senior',
    'senior_plus': 'senior_plus',
}


def predict_seniority(title: str, description: str) -> str:
    """Return a seniority label for a single job. Never raises."""
    try:
        text = f"{title} {description}"
        label = _get_pipeline().predict([text])[0]
        return _LABEL_MAP.get(label, 'not_stated')
    except Exception:
        return 'not_stated'
