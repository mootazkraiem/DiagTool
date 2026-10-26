"""Comparison of the candidate anomaly algorithms on the clean-2 split.

For every promoted family, the training and holdout recordings of its production
manifest are turned into canonical features, exactly as in clean_pipeline. Each CAN
identifier that has a production model is then fitted three times, on the same rows
and the same features: IsolationForest (production parameters), Local Outlier Factor
(novelty mode) and One Class SVM (RBF kernel). LOF and the SVM need a scaler, fitted
on the training rows; the forest does not.

All three are calibrated with the production rule (threshold = (k+1)-th smallest
training score, k = floor(0.02 x rows)) and scored on the holdout recording, which
none of them saw. There are no attack labels: the measures are the share of holdout
(normal) rows flagged, the training time, the batch scoring time per row and the time
of one single-frame call, as the live path makes it.

The One Class SVM does not scale to the largest identifiers (up to 1.1 million rows),
so every algorithm is fitted on at most --cap evenly spaced training rows of each
identifier. Holdout rows are all scored.

    python -m backend.ml.validation.compare_algorithms --cap 5000 --out report.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import calibrate_threshold
from backend.ml.training import clean_pipeline as cp

ASSETS = cp.ASSETS_ROOT
FAMILIES = ("jaguar_ipace", "kia_ev6", "nissan_leaf_2019", "road_ambient")
ALGORITHMS = ("isolation_forest", "lof", "one_class_svm")
TARGET = cp.TARGET_CONTAMINATION
SINGLE_CALLS = 20                     # single-frame calls timed per identifier and algorithm


class Fitted:
    """One fitted detector: training scores, and a score function for new rows."""

    def __init__(self, algorithm: str, x: np.ndarray):
        self.scaler = None
        if algorithm == "isolation_forest":
            self.model = IsolationForest(**cp.IFOREST_PARAMS).fit(x)
            self.train_scores = self.model.score_samples(x)
        elif algorithm == "lof":
            self.scaler = StandardScaler().fit(x)
            self.model = LocalOutlierFactor(n_neighbors=20, novelty=True).fit(self.scaler.transform(x))
            self.train_scores = self.model.negative_outlier_factor_
        elif algorithm == "one_class_svm":
            self.scaler = StandardScaler().fit(x)
            self.model = OneClassSVM(kernel="rbf", gamma="scale", nu=TARGET).fit(self.scaler.transform(x))
            self.train_scores = self.model.score_samples(self.scaler.transform(x))
        else:
            raise ValueError(algorithm)

    def score(self, x: np.ndarray) -> np.ndarray:
        return self.model.score_samples(self.scaler.transform(x) if self.scaler is not None else x)


def recordings_of(manifest: dict, by_path: dict) -> tuple[list, list]:
    def info(entry: dict, status: str) -> cp.RecordingInfo:
        rec = by_path[entry["path"]]
        return cp.RecordingInfo(rec.vehicle, entry["path"], rec.fmt, status,
                                content_sha256=entry["content_sha256"], frame_cap=entry.get("frame_cap"))
    return ([info(e, "train") for e in manifest["training_corpus"]["recordings"]],
            [info(e, "holdout") for e in manifest["holdout"]["recordings"]])


def features_of(infos: list) -> tuple[np.ndarray, np.ndarray]:
    parts = [cp.recording_features(i, ASSETS) for i in infos]
    return np.vstack([p[0] for p in parts]), np.concatenate([p[1] for p in parts])


def compare_family(family: str, by_path: dict, cap: int, log=print) -> dict:
    manifest = json.loads((ASSETS / "models" / family / "manifest.json").read_text(encoding="utf-8"))
    train_infos, hold_infos = recordings_of(manifest, by_path)
    t0 = time.perf_counter()
    x, ids = features_of(train_infos)
    xh, idh = features_of(hold_infos)
    log(f"{family}: features {len(x):,} training rows, {len(xh):,} holdout rows ({time.perf_counter() - t0:.0f} s)")

    per_algo = {a: {"fit_s": 0.0, "score_s": 0.0, "holdout_rows": 0, "flagged": 0,
                    "train_rows": 0, "single_call_ms": [], "per_id_flagged_share": {}} for a in ALGORITHMS}
    for key, entry in manifest["id_models"].items():
        cid = int(key, 16)
        index = [canonical.FEATURES.index(f) for f in entry["features"]]
        xi = x[ids == cid][:, index]
        if len(xi) > cap:
            xi = xi[np.unique(np.linspace(0, len(xi) - 1, cap).round().astype(int))]
        xhi = xh[idh == cid][:, index]
        for algo in ALGORITHMS:
            res = per_algo[algo]
            t = time.perf_counter()
            fitted = Fitted(algo, np.ascontiguousarray(xi))
            res["fit_s"] += time.perf_counter() - t
            res["train_rows"] += len(xi)
            if not np.isfinite(fitted.train_scores).all():
                raise ValueError(f"{family} {key} {algo}: non finite training scores")
            threshold = calibrate_threshold(fitted.train_scores, TARGET)["threshold"]
            if len(xhi):
                t = time.perf_counter()
                scores = fitted.score(xhi)
                res["score_s"] += time.perf_counter() - t
                flagged = int((scores < threshold).sum())
                res["holdout_rows"] += len(xhi)
                res["flagged"] += flagged
                res["per_id_flagged_share"][key] = flagged / len(xhi)
                rows = xhi[np.linspace(0, len(xhi) - 1, min(SINGLE_CALLS, len(xhi))).astype(int)]
                for row in rows:
                    t = time.perf_counter()
                    fitted.score(row.reshape(1, -1))
                    res["single_call_ms"].append((time.perf_counter() - t) * 1e3)
    out = {"family": family, "model_version": manifest["model_version"], "identifiers": len(manifest["id_models"]),
           "training_rows_total": int(len(x)), "holdout_rows_total": int(len(xh)), "algorithms": {}}
    for algo, res in per_algo.items():
        calls = np.array(res["single_call_ms"] or [np.nan])
        out["algorithms"][algo] = {
            "train_rows_used": res["train_rows"], "fit_s": res["fit_s"],
            "holdout_rows_scored": res["holdout_rows"], "flagged": res["flagged"],
            "flagged_share": res["flagged"] / res["holdout_rows"] if res["holdout_rows"] else None,
            "batch_score_us_per_row": 1e6 * res["score_s"] / res["holdout_rows"] if res["holdout_rows"] else None,
            "single_call_ms_median": float(np.nanmedian(calls)), "single_call_ms_p90": float(np.nanpercentile(calls, 90)),
            "per_id_flagged_share": res["per_id_flagged_share"],
        }
        a = out["algorithms"][algo]
        log(f"  {algo:<17} flagged {a['flagged_share']:.2%}  fit {a['fit_s']:7.1f} s  "
            f"batch {a['batch_score_us_per_row']:7.1f} us/row  one call {a['single_call_ms_median']:6.2f} ms")
    return out


def forest_feature_shares(families=FAMILIES) -> dict:
    """Share of the splits of the production forests that use each canonical feature,
    each split weighted by the training rows that reach it; every identifier counts once."""
    import joblib

    totals = {f: 0.0 for f in canonical.FEATURES}
    n_models = 0
    for family in families:
        manifest = json.loads((ASSETS / "models" / family / "manifest.json").read_text(encoding="utf-8"))
        models = joblib.load(ASSETS / "models" / family / "models.joblib")
        for key, model in models.items():
            kept = manifest["id_models"][key]["features"]
            weights = {f: 0.0 for f in kept}
            for est, feats in zip(model.estimators_, model.estimators_features_):
                tree = est.tree_
                for node in np.flatnonzero(tree.feature >= 0):
                    weights[kept[feats[tree.feature[node]]]] += tree.n_node_samples[node]
            total = sum(weights.values())
            if total:
                for f, w in weights.items():
                    totals[f] += w / total
                n_models += 1
    return {"models": n_models, "share": {f: v / n_models for f, v in totals.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=5000)
    ap.add_argument("--family", action="append", choices=FAMILIES)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    by_path = {cp._rel(r.path, ASSETS): r for r in cp.discover(ASSETS)}
    report = {"cap_training_rows_per_id": args.cap, "target_contamination": TARGET,
              "algorithms": {"isolation_forest": cp.IFOREST_PARAMS,
                             "lof": {"n_neighbors": 20, "novelty": True, "scaler": "StandardScaler"},
                             "one_class_svm": {"kernel": "rbf", "gamma": "scale", "nu": TARGET, "scaler": "StandardScaler"}},
              "families": [compare_family(f, by_path, args.cap) for f in (args.family or FAMILIES)],
              "forest_feature_shares": forest_feature_shares()}
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("written", args.out)


if __name__ == "__main__":
    main()
