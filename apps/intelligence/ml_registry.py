"""
Artifact registry — resolves which seniority model version is live.

Convention:
  ml/artifacts/seniority_<version>.joblib   — fitted Pipeline
  ml/artifacts/seniority_<version>.json     — sidecar metadata

The live version is recorded in ml/artifacts/live.txt (one line: the version string).
Django code loads the model through get_pipeline() and never hardcodes a filename.
"""
import json
import pathlib
import joblib

ARTIFACTS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "ml" / "artifacts"
_LIVE_PTR = ARTIFACTS_DIR / "live.txt"

_pipeline_cache: dict = {}


def live_version() -> str:
    return _LIVE_PTR.read_text().strip()


def model_path(version: str | None = None) -> pathlib.Path:
    v = version or live_version()
    return ARTIFACTS_DIR / f"seniority_{v}.joblib"


def metadata(version: str | None = None) -> dict:
    v = version or live_version()
    return json.loads((ARTIFACTS_DIR / f"seniority_{v}.json").read_text())


def get_pipeline(version: str | None = None):
    """Load and cache the pipeline for *version* (defaults to live)."""
    v = version or live_version()
    if v not in _pipeline_cache:
        _pipeline_cache[v] = joblib.load(model_path(v))
    return _pipeline_cache[v]
