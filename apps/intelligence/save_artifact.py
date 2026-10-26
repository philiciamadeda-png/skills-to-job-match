"""
Save a fitted seniority pipeline as a versioned artifact.

Usage:
    python apps/intelligence/save_artifact.py --version v1
"""
import argparse
import json
import subprocess
import sys
import os
import pathlib
from datetime import datetime, timezone

import django
import joblib
import sklearn

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

from apps.intelligence.models import Job
from apps.intelligence.ml_split import make_split

ARTIFACTS_DIR = pathlib.Path(__file__).resolve().parents[2] / "ml" / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def git_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except Exception:
        return "unknown"


def main(version: str, set_live: bool) -> None:
    # Load data
    df = pd.DataFrame(Job.objects.values("id", "title", "description", "seniority", "normalised_title"))
    df["company_name"] = pd.DataFrame(Job.objects.values("company__name"))["company__name"]
    df["text"] = df["title"] + " " + df["description"]

    X_train, X_test, y_train, y_test = make_split(df)

    # Train
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=10_000, ngram_range=(1, 2), sublinear_tf=True)),
        ("clf",   LogisticRegression(max_iter=1000, random_state=42)),
    ])
    pipe.fit(X_train, y_train)

    # Metrics
    report = classification_report(y_test, pipe.predict(X_test), output_dict=True, zero_division=0)

    # Save model
    model_file = ARTIFACTS_DIR / f"seniority_{version}.joblib"
    joblib.dump(pipe, model_file)

    # Save sidecar
    sidecar = {
        "version":        version,
        "trained_at":     datetime.now(timezone.utc).isoformat(),
        "git_commit":     git_hash(),
        "sklearn_version": sklearn.__version__,
        "joblib_version": joblib.__version__,
        "training_rows":  len(X_train),
        "test_rows":      len(X_test),
        "classes":        sorted(y_train.unique().tolist()),
        "metrics": {
            "accuracy":   round(report["accuracy"], 4),
            "macro_f1":   round(report["macro avg"]["f1-score"], 4),
            "per_class":  {
                cls: {k: round(report[cls][k], 4) for k in ("precision", "recall", "f1-score")}
                for cls in sorted(y_train.unique().tolist())
            },
        },
    }
    sidecar_file = ARTIFACTS_DIR / f"seniority_{version}.json"
    sidecar_file.write_text(json.dumps(sidecar, indent=2))

    print(f"Saved {model_file}")
    print(f"Saved {sidecar_file}")
    print(json.dumps(sidecar, indent=2))

    if set_live:
        (ARTIFACTS_DIR / "live.txt").write_text(version)
        print(f"\nlive.txt → {version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--set-live", action="store_true", default=True)
    args = parser.parse_args()
    main(args.version, args.set_live)
