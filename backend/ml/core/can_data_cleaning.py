from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


BYTE_COLS = [f"b{i}" for i in range(8)]


@dataclass
class CleaningConfig:
    min_can_id: int = 0
    max_can_id: int = 0x7FF
    min_can_occurrence: int = 5
    max_dt_quantile: float = 0.999
    use_isolation_forest: bool = True
    iforest_contamination: float = 0.005
    random_state: int = 42


def _record(step_rows: List[dict], step: str, before: int, after: int, reason: str) -> None:
    step_rows.append({"step": step, "reason": reason, "rows_before": int(before), "rows_after": int(after), "rows_removed": int(before - after)})


def clean_can_dataframe(
    df: pd.DataFrame,
    output_dir: Path,
    context: str,
    config: CleaningConfig | None = None,
    apply_outlier_filter: bool = False,
) -> pd.DataFrame:
    cfg = config or CleaningConfig()
    output_dir.mkdir(parents=True, exist_ok=True)

    work = df.copy()
    removed_rows: List[dict] = []
    step_rows: List[dict] = []

    # enforce required columns
    req = ["timestamp", "can_id", *BYTE_COLS]
    missing = [c for c in req if c not in work.columns]
    if missing:
        raise ValueError(f"[{context}] missing required raw columns: {missing}")

    # timestamp cleaning
    before = len(work)
    mask = pd.to_numeric(work["timestamp"], errors="coerce").notna()
    removed_rows.extend(work.loc[~mask].assign(remove_step="timestamp_missing", remove_reason="missing timestamp").to_dict("records"))
    work = work.loc[mask].copy()
    work["timestamp"] = pd.to_numeric(work["timestamp"], errors="coerce")
    _record(step_rows, "timestamp", before, len(work), "missing timestamp")

    work["can_id"] = pd.to_numeric(work["can_id"], errors="coerce")

    # payload/byte cleaning
    for c in BYTE_COLS:
        work[c] = pd.to_numeric(work[c], errors="coerce")
    before = len(work)
    mask = work[BYTE_COLS].notna().all(axis=1)
    removed_rows.extend(work.loc[~mask].assign(remove_step="payload_missing", remove_reason="missing payload bytes").to_dict("records"))
    work = work.loc[mask].copy()
    _record(step_rows, "payload", before, len(work), "missing payload")

    before = len(work)
    mask = ((work[BYTE_COLS] >= 0) & (work[BYTE_COLS] <= 255)).all(axis=1)
    removed_rows.extend(work.loc[~mask].assign(remove_step="byte_range", remove_reason="byte out of [0,255]").to_dict("records"))
    work = work.loc[mask].copy()
    work[BYTE_COLS] = work[BYTE_COLS].astype(int)
    _record(step_rows, "byte_sanitize", before, len(work), "out-of-range bytes")

    # CAN ID cleaning
    before = len(work)
    mask = work["can_id"].notna() & (work["can_id"] >= cfg.min_can_id) & (work["can_id"] <= cfg.max_can_id)
    removed_rows.extend(work.loc[~mask].assign(remove_step="can_id_invalid", remove_reason="invalid can_id").to_dict("records"))
    work = work.loc[mask].copy()
    _record(step_rows, "can_id", before, len(work), "invalid can_id")

    before = len(work)
    freq = work["can_id"].value_counts()
    keep_ids = set(freq[freq >= cfg.min_can_occurrence].index)
    removed_rows.extend(work.loc[~work["can_id"].isin(keep_ids)].assign(remove_step="can_id_low_freq", remove_reason="low-frequency can_id").to_dict("records"))
    work = work[work["can_id"].isin(keep_ids)].copy()
    _record(step_rows, "can_id_frequency", before, len(work), f"can_id occurrence < {cfg.min_can_occurrence}")

    # time-delta cleaning
    work = work.sort_values(["can_id", "timestamp"]).reset_index(drop=True)
    work["_dt"] = work.groupby("can_id")["timestamp"].diff()

    before = len(work)
    dup_mask = work["_dt"].eq(0)
    removed_rows.extend(work.loc[dup_mask].assign(remove_step="duplicate_timestamp", remove_reason="duplicate consecutive timestamp within CAN ID").to_dict("records"))
    work = work.loc[~dup_mask].copy()
    _record(step_rows, "timestamp_duplicate", before, len(work), "duplicate consecutive timestamps")

    before = len(work)
    neg_zero_mask = work["_dt"].notna() & (work["_dt"] <= 0)
    removed_rows.extend(work.loc[neg_zero_mask].assign(remove_step="non_positive_dt", remove_reason="non-positive time delta").to_dict("records"))
    work = work.loc[~neg_zero_mask].copy()
    _record(step_rows, "time_delta", before, len(work), "non-positive time delta")

    before = len(work)
    q = work.groupby("can_id")["_dt"].transform(lambda s: s.quantile(cfg.max_dt_quantile) if s.notna().sum() > 2 else np.nan)
    gap_mask = work["_dt"].notna() & q.notna() & (work["_dt"] > q)
    removed_rows.extend(work.loc[gap_mask].assign(remove_step="extreme_time_gap", remove_reason=f"dt above {cfg.max_dt_quantile} quantile per can_id").to_dict("records"))
    work = work.loc[~gap_mask].copy()
    _record(step_rows, "time_gap_clip", before, len(work), "extreme per-CAN-ID time gaps")

    work = work.drop(columns=["_dt"], errors="ignore")

    # optional outlier filtering for normal-training only
    if apply_outlier_filter and not work.empty:
        tmp = work.sort_values(["can_id", "timestamp"]).copy()
        tmp["_dt"] = tmp.groupby("can_id")["timestamp"].diff().fillna(0.0)
        tmp["_byte_mean"] = tmp[BYTE_COLS].mean(axis=1)
        tmp["_byte_std"] = tmp[BYTE_COLS].std(axis=1)
        feats = tmp[["_dt", "_byte_mean", "_byte_std"]].to_numpy(dtype=np.float64)

        med = np.median(feats, axis=0)
        mad = np.median(np.abs(feats - med), axis=0) + 1e-9
        robust_z = np.max(np.abs((feats - med) / mad), axis=1)
        mad_mask = robust_z <= 12.0

        before = len(tmp)
        removed_rows.extend(tmp.loc[~mad_mask].assign(remove_step="mad_outlier", remove_reason="catastrophic MAD outlier").to_dict("records"))
        tmp = tmp.loc[mad_mask].copy()
        _record(step_rows, "mad_filter", before, len(tmp), "catastrophic feature outliers")

        if cfg.use_isolation_forest and len(tmp) > 500:
            before = len(tmp)
            iso = IsolationForest(contamination=cfg.iforest_contamination, random_state=cfg.random_state, n_estimators=200)
            pred = iso.fit_predict(tmp[["_dt", "_byte_mean", "_byte_std"]].to_numpy(dtype=np.float64))
            keep = pred == 1
            removed_rows.extend(tmp.loc[~keep].assign(remove_step="iforest_outlier", remove_reason="isolation forest pre-cleaning").to_dict("records"))
            tmp = tmp.loc[keep].copy()
            _record(step_rows, "iforest_filter", before, len(tmp), "optional isolation-forest pre-clean")

        work = tmp.drop(columns=["_dt", "_byte_mean", "_byte_std"], errors="ignore")

    # output artifacts
    summary_df = pd.DataFrame(step_rows)
    removed_df = pd.DataFrame(removed_rows)
    before_after = pd.DataFrame([
        {"context": context, "rows_before": int(len(df)), "rows_after": int(len(work)), "rows_removed": int(len(df) - len(work)), "retention_rate": float(len(work) / max(1, len(df)))}
    ])

    summary_df.to_csv(output_dir / "cleaning_summary.csv", index=False)
    removed_df.to_csv(output_dir / "removed_rows_log.csv", index=False)
    before_after.to_csv(output_dir / "before_vs_after_stats.csv", index=False)

    top_removed_ids = []
    if not removed_df.empty and "can_id" in removed_df.columns:
        top_removed_ids = removed_df["can_id"].value_counts().head(10).to_dict()

    print(f"[INFO][CLEAN][{context}] total rows removed: {len(df) - len(work)}")
    for _, row in summary_df.iterrows():
        print(f"[INFO][CLEAN][{context}] step={row['step']} removed={int(row['rows_removed'])} reason={row['reason']}")
    print(f"[INFO][CLEAN][{context}] retention_rate={float(len(work)/max(1,len(df))):.4f}")
    print(f"[INFO][CLEAN][{context}] top removed CAN IDs: {top_removed_ids}")

    return work.reset_index(drop=True)
