"""LightGBM fire-risk inference loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import joblib
import lightgbm as lgb
import numpy as np


DEFAULT_STATIC_RISK_CUTOFFS: dict[str, float] = {
    "Extremo": 0.057850664396194046,
    "Alto": 0.012920176782054635,
    "Moderado": 0.0035496501995956643,
}


def compute_daily_percentile_cutoffs(
    reference_probs: np.ndarray,
    static_cutoffs: dict[str, float],
    *,
    top_frac_extremo: float = 0.0005,
    top_frac_alto: float = 0.004,
    top_frac_moderado: float = 0.025,
    floor_extremo: float = 0.015,
    floor_alto: float = 0.013,
    floor_moderado: float = 0.0005,
    min_samples: int = 100,
) -> dict[str, float]:
    """Compute bounded daily-percentile cutoffs from `reference_probs`.

    Lowers thresholds when predicted probabilities sit below static validation cutoffs,
    caps at static cutoffs during severe outbreaks, clamps above safety floors on
    quiet or near-zero days, and falls back to static cutoffs on small or degenerate inputs.
    """
    vals = np.asarray(reference_probs, dtype=np.float64).ravel()
    vals = vals[np.isfinite(vals)]
    if vals.size < min_samples:
        return dict(static_cutoffs)

    vmin = float(np.min(vals))
    vmax = float(np.max(vals))
    if vmax - vmin <= 1e-12:
        return dict(static_cutoffs)

    q_mod = float(np.quantile(vals, 1.0 - top_frac_moderado))
    q_alt = float(np.quantile(vals, 1.0 - top_frac_alto))
    q_ext = float(np.quantile(vals, 1.0 - top_frac_extremo))
    if q_mod <= vmin + 1e-12:
        return dict(static_cutoffs)

    mod = min(static_cutoffs["Moderado"], max(floor_moderado, q_mod))
    alt = min(static_cutoffs["Alto"], max(floor_alto, q_alt))
    ext = min(static_cutoffs["Extremo"], max(floor_extremo, q_ext))

    alt = max(alt, mod)
    ext = max(ext, alt)
    return {"Extremo": float(ext), "Alto": float(alt), "Moderado": float(mod)}


@dataclass
class FireRiskPredictor:
    """Self-contained predictor loaded from `fire_risk_bundle.joblib`."""

    model_version: str
    feature_columns: list[str]
    logit_offset: float
    risk_cutoffs: dict[str, float]
    model_str: str

    def __post_init__(self) -> None:
        self._booster = lgb.Booster(model_str=self.model_str)

    @classmethod
    def from_bundle(cls, bundle_path: Path) -> FireRiskPredictor:
        payload = joblib.load(bundle_path)
        return cls(
            model_version=str(payload["model_version"]),
            feature_columns=list(payload["feature_columns"]),
            logit_offset=float(payload["logit_offset"]),
            risk_cutoffs={k: float(v) for k, v in payload["risk_cutoffs"].items()},
            model_str=str(payload["model_str"]),
        )

    def _raw_to_prob(self, raw: np.ndarray) -> np.ndarray:
        z = np.clip(raw + self.logit_offset, -40.0, 40.0)
        return (1.0 / (1.0 + np.exp(-z))).astype(np.float32)

    def predict_probabilities(self, X: np.ndarray) -> np.ndarray:
        """Return calibrated probabilities `p in (0, 1)` for feature matrix `X`."""
        raw = self._booster.predict(np.asarray(X, dtype=np.float32), raw_score=True)
        return self._raw_to_prob(raw)

    def predict_with_stability(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return `(probs, stability)` where `stability in [0.2, 1.0]` measures tree-depth agreement."""
        X_arr = np.asarray(X, dtype=np.float32)
        total_trees = int(self._booster.num_trees())
        if total_trees < 3:
            probs = self.predict_probabilities(X_arr)
            return probs, np.ones(len(probs), dtype=np.float32)

        cuts = (max(1, total_trees // 2), max(1, (total_trees * 3) // 4), total_trees)
        probs_by_cut = [
            self._raw_to_prob(self._booster.predict(X_arr, raw_score=True, num_iteration=k))
            for k in cuts
        ]
        stacked = np.vstack(probs_by_cut)
        spread = np.max(stacked, axis=0) - np.min(stacked, axis=0)
        stability = np.clip(1.0 - (spread / 0.25), 0.2, 1.0).astype(np.float32)
        return probs_by_cut[-1], stability

    def compute_daily_percentile_cutoffs(
        self,
        reference_probs: np.ndarray,
        *,
        top_frac_extremo: float = 0.0005,
        top_frac_alto: float = 0.004,
        top_frac_moderado: float = 0.025,
        floor_extremo: float = 0.015,
        floor_alto: float = 0.013,
        floor_moderado: float = 0.0005,
        min_samples: int = 100,
    ) -> dict[str, float]:
        """Compute bounded daily-percentile cutoffs from `reference_probs`."""
        return compute_daily_percentile_cutoffs(
            reference_probs,
            self.risk_cutoffs,
            top_frac_extremo=top_frac_extremo,
            top_frac_alto=top_frac_alto,
            top_frac_moderado=top_frac_moderado,
            floor_extremo=floor_extremo,
            floor_alto=floor_alto,
            floor_moderado=floor_moderado,
            min_samples=min_samples,
        )

    def categorize(
        self,
        prob: np.ndarray,
        cutoffs: dict[str, float] | None = None,
    ) -> np.ndarray:
        """Map probabilities to (`Extremo`, `Alto`, `Moderado`, `Bajo`)."""
        c = cutoffs if cutoffs is not None else self.risk_cutoffs
        return np.where(
            prob >= c["Extremo"],
            "Extremo",
            np.where(
                prob >= c["Alto"],
                "Alto",
                np.where(prob >= c["Moderado"], "Moderado", "Bajo"),
            ),
        )
