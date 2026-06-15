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


class LLMExplainer:
    def __init__(self, model: str) -> None:
        self.model = model
        self._api_key: str | None = os.environ.get("OPENAI_API_KEY")

    def explain(self, context: dict) -> dict[str, str]:
        can_id = context.get("can_id", "unknown")
        score = float(context.get("anomaly_score", 0.0))
        cluster = context.get("cluster", 0)
        top_feature = context.get("top_feature", "unknown")

        if self._api_key:
            try:
                return self._explain_openai(can_id, score, cluster, top_feature, context)
            except Exception as exc:
                logger.warning("[LLM] OpenAI call failed, falling back to template: %s", exc)

        return self._explain_template(can_id, score, cluster, top_feature)

    def explain_alert(self, alert: dict) -> dict[str, str]:
        """Explain a live IDS alert (from live_alerts_buffer) with GPT-4o-mini."""
        can_id = alert.get("can_id", "unknown")
        score = float(alert.get("score", 0.0))
        severity = alert.get("severity", "UNKNOWN")
        attack_type = alert.get("attack_type", "runtime")
        reason = alert.get("reason", "")
        dominant_layer = alert.get("dominant_detection_layer", "unknown")

        if self._api_key:
            try:
                return self._explain_alert_openai(can_id, score, severity, attack_type, reason, dominant_layer)
            except Exception as exc:
                logger.warning("[LLM] OpenAI alert call failed, falling back to template: %s", exc)

        return self._explain_alert_template(can_id, score, severity, attack_type, reason, dominant_layer)

    def _explain_openai(self, can_id: str, score: float, cluster: int, top_feature: str, context: dict) -> dict[str, str]:
        import openai
        client = openai.OpenAI(api_key=self._api_key)
        prompt = (
            f"You are an automotive cybersecurity AI analyst. Explain this CAN bus anomaly concisely.\n"
            f"CAN-ID: {can_id} | Anomaly Score: {score:.3f} | Cluster: {cluster} | Top Feature: {top_feature}\n"
            f"Context: {json.dumps({k: v for k, v in context.items() if k not in ('raw_bytes',)}, default=str)[:400]}\n\n"
            f"Respond in JSON with keys: summary (1 sentence), detail (2-3 sentences), recommendation (1 sentence)."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0.3,
        )
        result = json.loads(resp.choices[0].message.content or "{}")
        return {
            "summary":        result.get("summary", f"CAN-ID {can_id} anomaly score={score:.3f}"),
            "detail":         result.get("detail", ""),
            "recommendation": result.get("recommendation", "Inspect frames from this CAN-ID."),
        }

    def _explain_alert_openai(self, can_id: str, score: float, severity: str, attack_type: str, reason: str, dominant_layer: str) -> dict[str, str]:
        import openai
        client = openai.OpenAI(api_key=self._api_key)
        prompt = (
            f"You are an automotive intrusion detection system analyst. Explain this IDS alert.\n"
            f"CAN-ID: {can_id} | Fusion Score: {score:.3f} | Severity: {severity} | "
            f"Attack Type: {attack_type} | Dominant Layer: {dominant_layer}\n"
            f"Detection reason: {reason[:300]}\n\n"
            f"Provide a professional security analysis. "
            f"Respond in JSON with keys: summary (1 sentence), detail (2-3 sentences explaining the attack vector), "
            f"recommendation (1 sentence of mitigation advice)."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=350,
            temperature=0.3,
        )
        result = json.loads(resp.choices[0].message.content or "{}")
        return {
            "summary":        result.get("summary", f"{severity} alert on {can_id}, score={score:.3f}"),
            "detail":         result.get("detail", ""),
            "recommendation": result.get("recommendation", "Isolate the affected CAN segment and review frame injection patterns."),
        }

    @staticmethod
    def _explain_template(can_id: str, score: float, cluster: int, top_feature: str) -> dict[str, str]:
        return {
            "summary": f"CAN-ID {can_id} produced an anomaly score of {score:.3f} (cluster {cluster}).",
            "detail": (
                f"The dominant anomalous feature was '{top_feature}'. "
                f"Score {score:.3f} indicates {'critical' if score >= 0.8 else 'elevated' if score >= 0.55 else 'low-level'} risk. "
                f"The IsolationForest model assigned this frame to an outlier cluster."
            ),
            "recommendation": "Inspect frames from this CAN-ID for injection patterns and verify against known-good baselines.",
        }

    @staticmethod
    def _explain_alert_template(can_id: str, score: float, severity: str, attack_type: str, reason: str, dominant_layer: str) -> dict[str, str]:
        severity_desc = {"CRITICAL": "critical intrusion", "HIGH": "high-risk anomaly", "WARNING": "elevated alert"}.get(severity, "anomaly")
        layer_desc = {"timing": "inter-frame timing deviation", "payload": "abnormal payload entropy", "ml": "ML outlier classification", "temporal": "temporal persistence pattern"}.get(dominant_layer, "multi-layer fusion")
        return {
            "summary": f"A {severity_desc} was detected on CAN-ID {can_id} with fusion score {score:.3f} via {layer_desc}.",
            "detail": (
                f"Attack classification: {attack_type}. "
                f"The dominant detection signal was {layer_desc} ({dominant_layer} layer). "
                f"Raw scores: {reason[:200] or 'unavailable'}. "
                f"Score {score:.3f} {'exceeds the critical threshold (0.80)' if score >= 0.8 else 'exceeds the alert threshold (0.55)' if score >= 0.55 else 'exceeds the elevated threshold (0.35)'}."
            ),
            "recommendation": (
                "Isolate the CAN segment carrying this ID, capture raw frames for forensic analysis, "
                "and cross-reference against the vehicle's expected DBC signal map."
            ),
        }

    def explain_anomaly(self, anomaly_data: dict) -> str:
        return self.explain(anomaly_data).get("summary", "")


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
