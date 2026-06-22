from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

try:
    from backend.ml.feature_engineering import load_kaggle_dataset, preprocess_pipeline
    from backend.ml.state_based_pipeline import infer
    from backend.progress import print_progress
except Exception:
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from backend.ml.feature_engineering import load_kaggle_dataset, preprocess_pipeline
    from backend.ml.state_based_pipeline import infer
    from backend.progress import print_progress


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_ROOT = PROJECT_ROOT / "assets" / "archive"
MODEL_ROOT = PROJECT_ROOT / "assets" / "models"
SUMMARY_PATH = MODEL_ROOT / "evaluation_summary.csv"
PLOT_ROOT = MODEL_ROOT / "pca_state_plots"
EXPECTED_FEATURES = [
    "time_diff",
    "rolling_std_time_diff",
    "byte_diff",
    "changed_bytes_count",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate state-based CAN anomaly models directly from raw CAN log input.")
    parser.add_argument("--log-root", type=Path, default=LOG_ROOT)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--plot-root", type=Path, default=PLOT_ROOT)
    return parser.parse_args()


def iter_log_files(log_root: Path) -> list[Path]:
    return sorted(p for p in log_root.rglob("*.txt") if p.is_file())


def _safe_pca(X: np.ndarray, feature_names: list[str]) -> tuple[np.ndarray | None, np.ndarray | None, list[str]]:
    if X.shape[1] < 2:
        print(f"[WARN] PCA skipped: only {X.shape[1]} feature(s) available")
        return None, None, []

    variances = np.var(X, axis=0)
    keep_mask = variances > 1e-6
    dropped = [feature_names[i] for i, keep in enumerate(keep_mask.tolist()) if not keep]
    kept = [feature_names[i] for i, keep in enumerate(keep_mask.tolist()) if keep]
    print(f"[INFO] features_before={len(feature_names)} features_after={len(kept)} dropped={dropped}")

    X2 = X[:, keep_mask]
    if X2.shape[1] < 2:
        print(f"[WARN] PCA skipped after variance filter: only {X2.shape[1]} feature(s)")
        return None, None, dropped

    pca = PCA(n_components=min(2, X2.shape[1]), random_state=42)
    X_pca = pca.fit_transform(X2)
    print(f"[INFO] PCA explained_variance_ratio={pca.explained_variance_ratio_}")
    if pca.explained_variance_ratio_[0] > 0.98:
        print("[WARN] PCA collapsed to 1D")
    return X_pca, pca.explained_variance_ratio_, dropped


def main() -> None:
    args = parse_args()
    files = iter_log_files(args.log_root)
    if not files:
        print(f"[ERROR] no raw CAN log files found in: {args.log_root}")
        return

    out_rows: list[dict[str, object]] = []
    args.plot_root.mkdir(parents=True, exist_ok=True)

    total = len(files)
    for idx, path in enumerate(files, start=1):
        print_progress("EVAL", "validation", idx, total, path.name)
        try:
            raw = load_kaggle_dataset(path)
            vehicle = path.stem
            print(f"[INFO] file={path.name} vehicle={vehicle}")

            feat_df, _, _ = preprocess_pipeline(raw, scaler=None, fit=True)
            if feat_df.empty:
                print(f"[CRITICAL] {path.name} -> empty after preprocessing")
                continue

            scored = infer(feat_df, vehicle)
            if scored.empty:
                print(f"[CRITICAL] {path.name} -> empty after infer")
                continue

            scored["state"] = scored["state"].astype(str).str.lower().str.strip()
            print(f"[INFO] state_counts={scored['state'].value_counts(dropna=False).to_dict()}")

            for state, g in scored.groupby("state", sort=False):
                rows = int(len(g))
                anomalies = int((g["is_anomaly"] == 1).sum())
                out_rows.append(
                    {
                        "source_file": path.name,
                        "state": state,
                        "rows": rows,
                        "anomalies": anomalies,
                        "anomaly_ratio_percent": round((anomalies / rows) * 100.0 if rows else 0.0, 6),
                    }
                )

            for state in ["idle", "parking", "driving"]:
                sdf = scored[scored["state"] == state].copy()
                if sdf.empty:
                    print(f"[WARN] {path.name} -> missing state '{state}'")
                    continue

                missing = [f for f in EXPECTED_FEATURES if f not in sdf.columns]
                if missing:
                    raise ValueError(f"Missing features: {missing} | file={path.name} | state={state}")
                if any(c in sdf.columns for c in [f"b{i}" for i in range(8)]):
                    raise ValueError(f"Raw byte leakage detected | file={path.name} | state={state}")

                X = sdf[EXPECTED_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=np.float64)
                for i, name in enumerate(EXPECTED_FEATURES):
                    col = X[:, i]
                    cmin = float(np.min(col))
                    cmax = float(np.max(col))
                    cstd = float(np.std(col))
                    print(f"[SANITY] {name}: min={cmin:.6f}, max={cmax:.6f}, std={cstd:.6f}")
                    if abs(cmax) > 20 or abs(cmin) > 20:
                        print(f"[WARNING] {name} abs(max) > 20")
                    if cstd < 1e-3:
                        print(f"[WARNING] {name} std < 1e-3")
                scaler = RobustScaler()
                X_scaled = scaler.fit_transform(X)
                print(f"[INFO] rows_after_clean={len(sdf)} can_ids={sdf['can_id'].nunique()} feature_size={X_scaled.shape[1]}")

                X_pca, explained, dropped = _safe_pca(X_scaled, EXPECTED_FEATURES)
                if X_pca is None:
                    continue

                model = IsolationForest(contamination=0.02, random_state=42)
                pred = model.fit_predict(X_scaled)
                anomaly_count = int((pred == -1).sum())
                print(f"[INFO] anomaly_count={anomaly_count}/{len(pred)}")

                fig, ax = plt.subplots(figsize=(9, 6))
                mask_anom = pred == -1
                ax.scatter(X_pca[~mask_anom, 0], X_pca[~mask_anom, 1], s=8, alpha=0.35, c="#2563eb", label="normal")
                ax.scatter(X_pca[mask_anom, 0], X_pca[mask_anom, 1], s=12, alpha=0.8, c="#dc2626", label="anomaly")
                ax.set_title(f"{vehicle.upper()} {state.upper()} PCA")
                ax.set_xlabel("PCA1")
                ax.set_ylabel("PCA2")
                ax.legend()
                ax.grid(alpha=0.2)
                fig.tight_layout()
                out_plot = args.plot_root / f"pca_{vehicle.strip().lower().replace(' ', '_')}_{state}.png"
                fig.savefig(out_plot, dpi=150)
                plt.close(fig)

        except Exception as exc:
            print()
            print(f"[ERROR][EVAL] {path.name} ({exc})")
            raise
    print()

    if out_rows:
        summary_df = pd.DataFrame(out_rows)
        args.summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_df.to_csv(args.summary_path, index=False)
        print(f"[INFO] saved summary: {args.summary_path}")
    else:
        print("[ERROR] no evaluation rows generated")


if __name__ == "__main__":
    main()
