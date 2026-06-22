from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Must stay in sync with core/feature_engineering.py FEATURE_COLS
FEATURE_COLS = [
    "time_diff",
    "rolling_std_time_diff",
    "rolling_mean_byte_diff",
    "rolling_byte_diff_std",
    "rolling_max_byte_diff",
    "msg_frequency",
    "byte_diff",
    "changed_bytes_count",
    "msg_rate",
    "rolling_var_time_diff",
    "burstiness",
    "can_id_entropy",
    "payload_entropy",
    "inter_arrival_cv",
]


class AnalyzeCache:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def fingerprint(self, raw_bytes: bytes) -> str:
        return hashlib.sha1(raw_bytes, usedforsecurity=False).hexdigest()

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value


class FeedbackStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def add_feedback(self, feedback: dict) -> None:
        self.append(feedback)


class _ModelBundle:
    """Internal container for the fitted IsolationForest + KMeans models."""

    def __init__(self, n_clusters: int) -> None:
        self.n_clusters = n_clusters
        self._if_model: Any = None
        self._kmeans: Any = None
        self._feature_cols: list[str] = []


class VehicleAIDiagnosticEngine:
    def __init__(
        self,
        contamination: float = 0.01,
        n_clusters: int = 5,
        random_state: int = 42,
    ) -> None:
        self.contamination = contamination
        self._n_clusters = n_clusters
        self.random_state = random_state
        self.model_bundle: _ModelBundle | None = None

    def fit(self, df: pd.DataFrame, auto_clusters: bool = True) -> None:
        try:
            from sklearn.cluster import KMeans
            from sklearn.ensemble import IsolationForest
        except ImportError:
            logger.warning("[ENGINE] scikit-learn not available; model not trained")
            self.model_bundle = _ModelBundle(self._n_clusters)
            return

        cols = [c for c in FEATURE_COLS if c in df.columns]
        if not cols or df.empty:
            self.model_bundle = _ModelBundle(self._n_clusters)
            return

        x = df[cols].replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=np.float32)

        n_clusters = self._n_clusters
        if auto_clusters:
            n_clusters = max(2, min(n_clusters, max(2, len(x) // 100 + 1)))

        bundle = _ModelBundle(n_clusters)
        bundle._feature_cols = cols

        try:
            bundle._kmeans = KMeans(
                n_clusters=n_clusters, random_state=self.random_state, n_init=10
            )
            bundle._kmeans.fit(x)
        except Exception as exc:
            logger.warning("[ENGINE] KMeans fit failed: %s", exc)

        try:
            bundle._if_model = IsolationForest(
                n_estimators=100,
                contamination=self.contamination,
                random_state=self.random_state,
                n_jobs=1,
            )
            bundle._if_model.fit(x)
        except Exception as exc:
            logger.warning("[ENGINE] IsolationForest fit failed: %s", exc)

        self.model_bundle = bundle
        logger.info(
            "[ENGINE] Fit complete: rows=%d, features=%d, clusters=%d",
            len(x),
            len(cols),
            n_clusters,
        )

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["anomaly"] = 1
        out["cluster"] = 0
        out["anomaly_score"] = 0.0

        if self.model_bundle is None or self.model_bundle._if_model is None:
            return out

        cols = [c for c in self.model_bundle._feature_cols if c in out.columns]
        if not cols:
            return out

        x = out[cols].replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=np.float32)

        try:
            # -1 = anomaly, 1 = normal (sklearn convention)
            out["anomaly"] = self.model_bundle._if_model.predict(x)
            # score_samples returns negative values; flip so higher = more anomalous
            raw_scores = -self.model_bundle._if_model.score_samples(x)
            # Normalize to [0, 1] range
            lo, hi = float(raw_scores.min()), float(raw_scores.max())
            span = max(hi - lo, 1e-6)
            out["anomaly_score"] = (raw_scores - lo) / span
        except Exception as exc:
            logger.warning("[ENGINE] IsolationForest predict failed: %s", exc)

        if self.model_bundle._kmeans is not None:
            try:
                out["cluster"] = self.model_bundle._kmeans.predict(x)
            except Exception as exc:
                logger.warning("[ENGINE] KMeans predict failed: %s", exc)

        return out

    def save(self, path: Path) -> None:
        """Persist the fitted model bundle to disk so the next startup skips retraining."""
        if self.model_bundle is None or self.model_bundle._if_model is None:
            logger.warning("[ENGINE] save() called but no fitted model — skipping")
            return
        try:
            import joblib
            path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {
                    "if_model": self.model_bundle._if_model,
                    "kmeans": self.model_bundle._kmeans,
                    "feature_cols": self.model_bundle._feature_cols,
                    "n_clusters": self.model_bundle.n_clusters,
                },
                path,
            )
            logger.info("[ENGINE] Model saved → %s", path)
        except Exception as exc:
            logger.warning("[ENGINE] Model save failed: %s", exc)

    def load(self, path: Path) -> bool:
        """Restore a previously saved model bundle. Returns True on success."""
        try:
            import joblib
            data = joblib.load(path)
            bundle = _ModelBundle(data.get("n_clusters", self._n_clusters))
            bundle._if_model = data.get("if_model")
            bundle._kmeans = data.get("kmeans")
            bundle._feature_cols = data.get("feature_cols", [])
            self.model_bundle = bundle
            logger.info(
                "[ENGINE] Model loaded ← %s (features=%d, clusters=%d)",
                path,
                len(bundle._feature_cols),
                bundle.n_clusters,
            )
            return True
        except Exception as exc:
            logger.debug("[ENGINE] Model load skipped (expected on first run): %s", exc)
            return False

    def build_anomaly_context(self, predicted: pd.DataFrame) -> list[dict]:
        anomalous = predicted[predicted["anomaly"] == -1]
        if anomalous.empty:
            return []

        cols = [c for c in FEATURE_COLS if c in anomalous.columns]
        contexts: list[dict] = []
        for _, row in anomalous.iterrows():
            feature_vals = {c: float(row[c]) for c in cols}
            top_feature = max(feature_vals, key=feature_vals.get) if feature_vals else "unknown"
            ctx: dict[str, Any] = {
                "can_id": f"0x{int(row['can_id']):03X}" if "can_id" in row else "unknown",
                "timestamp": float(row.get("timestamp", 0.0)),
                "cluster": int(row.get("cluster", 0)),
                "anomaly_score": float(row.get("anomaly_score", 0.0)),
                "top_feature": top_feature,
            }
            ctx.update(feature_vals)
            contexts.append(ctx)

        return contexts


def collect_can_logs_from_assets(
    assets_root: Path,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    from backend.data_processing.parser import CanLogParser

    stats: Dict[str, Any] = {"files_found": 0, "rows_parsed": 0}

    log_files = []
    for suffix in [".log", ".txt", ".trc", ".asc", ".csv", ".crtd"]:
        log_files.extend(assets_root.glob(f"**/*{suffix}"))

    stats["files_found"] = len(log_files)
    if not log_files:
        return pd.DataFrame(), stats

    all_dfs: list[pd.DataFrame] = []
    for log_file in log_files[:5]:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                df, file_stats = CanLogParser.parse_stream(f, log_file.name, max_lines=10000)
            if not df.empty:
                all_dfs.append(df)
                stats["rows_parsed"] += file_stats.lines_parsed
        except Exception as exc:
            logger.warning("Error parsing %s: %s", log_file, exc)

    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True), stats
    return pd.DataFrame(), stats
