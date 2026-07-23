"""
Serve the registry's active ensemble version (issues #5/#6 -> #7).

Loads joblib artifacts for the active version and produces the probability
of 'long' for a feature row — the same interface the baseline model fills
when no trained model is available.
"""

import json
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np
import pandas as pd

from app.models.ensemble_trainer import predict_prob_long


class EnsemblePredictor:
    def __init__(self, version_id: str, models: Dict[str, object],
                 feature_columns: list):
        self.version_id = version_id
        self.models = models
        self.feature_columns = feature_columns

    def prob_long(self, features_row: pd.DataFrame) -> float:
        X = features_row[self.feature_columns]
        return float(predict_prob_long(self.models, X)[0])

    def member_votes(self, features_row: pd.DataFrame) -> Dict[str, str]:
        X = features_row[self.feature_columns]
        return {
            name: "long" if model.predict_proba(X)[0, 1] >= 0.5 else "flat"
            for name, model in self.models.items()
        }


def load_active(registry_root) -> Optional[EnsemblePredictor]:
    """Load the active version from a registry directory, or None."""
    root = Path(registry_root)
    index_path = root / "registry.json"
    if not index_path.exists():
        return None
    index = json.loads(index_path.read_text())
    version_id = index.get("active")
    if not version_id:
        return None
    artifact_dir = root / version_id
    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    models = {
        path.stem: joblib.load(path)
        for path in sorted(artifact_dir.glob("*.joblib"))
    }
    if not models:
        return None
    return EnsemblePredictor(version_id, models, manifest["feature_columns"])
