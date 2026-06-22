from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from backend.ml.feature_engineering import load_kaggle_dataset
except ModuleNotFoundError:
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.feature_engineering import load_kaggle_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSETS_ROOT = PROJECT_ROOT / "assets"
ARCHIVE_ROOT = ASSETS_ROOT / "archive"
TESLA_DBC = ASSETS_ROOT / "dbc_files" / "can1-tesla-model-3.dbc"
TESLA_LOG = ASSETS_ROOT / "EV-CANlogs-main" / "Tesla" / "Model 3" / "tesla-model3-battery-only.log.log"
OUT_ROOT = ASSETS_ROOT / "evaluation" / "behavioral_timing"

ATTACK_FILES = {
    "DoS": "DoS_dataset.csv",
    "Fuzzy": "Fuzzy_dataset.csv",
    "RPM": "RPM_dataset.csv",
    "gear": "gear_dataset.csv",
}

BYTE_COLS = [f"b{i}" for i in range(8)]
TOP_N_IDS = 20


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--normal", type=Path, default=ARCHIVE_ROOT / "normal_run_data.txt")
    p.add_argument("--archive", type=Path, default=ARCHIVE_ROOT)
    p.add_argument("--tesla-dbc", type=Path, default=TESLA_DBC)
    p.add_argument("--tesla-log", type=Path, default=TESLA_LOG)
    p.add_argument("--out", type=Path, default=OUT_ROOT)
    return p.parse_args()


def _safe_hex_to_int(v: object) -> float:
    if pd.isna(v):
        return np.nan
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none"}:
        return np.nan
    try:
        return float(int(s, 16))
    except Exception:
        return np.nan


def load_attack_raw(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, header=None, low_memory=False)
    raw.columns = [f"c{i}" for i in range(raw.shape[1])]
    out = pd.DataFrame()
    out["timestamp"] = pd.to_numeric(raw["c0"], errors="coerce")
    out["can_id"] = raw["c1"].apply(_safe_hex_to_int)
    dlc = pd.to_numeric(raw["c2"], errors="coerce")
    for i in range(8):
        out[f"b{i}"] = raw[f"c{i+3}"].apply(_safe_hex_to_int)
    out = out[dlc == 8].dropna().reset_index(drop=True)
    out["timestamp"] -= float(out["timestamp"].min())
    return out


def parse_tesla_dbc_categories(path: Path) -> dict[str, list[int]]:
    cat_patterns = {
        "steering": re.compile(r"steer", re.IGNORECASE),
        "wheel_speed": re.compile(r"wheel.?speed", re.IGNORECASE),
        "torque": re.compile(r"torque", re.IGNORECASE),
        "brake": re.compile(r"brake|epb|ibst", re.IGNORECASE),
        "temperature": re.compile(r"temp|thermal|coolant|heat", re.IGNORECASE),
        "gear": re.compile(r"gear", re.IGNORECASE),
        "esp": re.compile(r"esp|yaw|stability", re.IGNORECASE),
        "battery_powertrain": re.compile(r"\bbms\b|drive|hv|dcdc|pcs|inverter|motor|battery", re.IGNORECASE),
    }
    category_ids: dict[str, set[int]] = {k: set() for k in cat_patterns}
    bo_re = re.compile(r"^BO_\s+(\d+)\s+([^:]+):\s*(\d+)\s+(\S+)")
    sg_re = re.compile(r"^\s*SG_\s+([^:]+)\s*:")
    current_id: int | None = None
    current_name = ""
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        bm = bo_re.match(ln)
        if bm:
            current_id = int(bm.group(1))
            current_name = bm.group(2).strip()
            for cat, pat in cat_patterns.items():
                if pat.search(current_name):
                    category_ids[cat].add(current_id)
            continue
        sm = sg_re.match(ln)
        if sm and current_id is not None:
            sname = sm.group(1).strip()
            for cat, pat in cat_patterns.items():
                if pat.search(sname):
                    category_ids[cat].add(current_id)
    return {k: sorted(v) for k, v in category_ids.items()}


def parse_tesla_log(path: Path) -> pd.DataFrame:
    line_re = re.compile(r"^\((?P<ts>[0-9]+\.[0-9]+)\)\s+\S+\s+(?P<canid>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)$")
    rows = []
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = line_re.match(ln.strip())
        if not m:
            continue
        ts = float(m.group("ts"))
        cid = int(m.group("canid"), 16)
        data_hex = m.group("data")
        if len(data_hex) % 2 != 0:
            continue
        payload = bytes.fromhex(data_hex) if data_hex else b""
        rows.append((ts, cid, payload))
    df = pd.DataFrame(rows, columns=["timestamp_abs", "can_id", "payload"])
    if df.empty:
        return df
    df["timestamp"] = df["timestamp_abs"] - float(df["timestamp_abs"].min())
    return df[["timestamp", "can_id", "payload"]]


def hamming_distance(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    d = 0
    for i in range(n):
        d += int((a[i] ^ b[i]).bit_count())
    d += 8 * abs(len(a) - len(b))
    return d


def payload_entropy(payloads: list[bytes]) -> float:
    if not payloads:
        return 0.0
    vals = np.zeros(256, dtype=np.float64)
    total = 0
    for p in payloads:
        for b in p:
            vals[b] += 1
            total += 1
    if total == 0:
        return 0.0
    probs = vals[vals > 0] / total
    return float(-(probs * np.log2(probs)).sum())


def build_per_id_profiles(df: pd.DataFrame) -> dict[int, dict[str, float]]:
    profiles: dict[int, dict[str, float]] = {}
    grouped = df.groupby("can_id", sort=False)
    total_duration = max(float(df["timestamp"].max() - df["timestamp"].min()), 1e-6)
    for can_id, g in grouped:
        g = g.sort_values("timestamp").reset_index(drop=True)
        ts = g["timestamp"].to_numpy(dtype=np.float64)
        dt = np.diff(ts)
        dt = dt[dt > 0]
        if len(dt) == 0:
            continue
        payloads = [bytes(int(v) for v in row) for row in g[BYTE_COLS].to_numpy(dtype=np.uint8)]
        hd = []
        byte_change_rate = []
        for i in range(1, len(payloads)):
            prev, cur = payloads[i - 1], payloads[i]
            hd.append(hamming_distance(prev, cur))
            changed = sum(1 for a, b in zip(prev, cur) if a != b)
            byte_change_rate.append(changed / 8.0)
        ent = payload_entropy(payloads)
        # rolling entropy on short windows
        win = 32
        ents = []
        for i in range(0, len(payloads), max(1, win // 2)):
            chunk = payloads[i : i + win]
            if len(chunk) >= 4:
                ents.append(payload_entropy(chunk))
        payload_hex = [p.hex() for p in payloads]
        repetition_ratio = float(pd.Series(payload_hex).value_counts(normalize=True).iloc[0])
        mean_period = float(np.mean(dt))
        std_period = float(np.std(dt))
        mean_freq = float(1.0 / max(mean_period, 1e-9))
        jitter = float(std_period / max(mean_period, 1e-9))
        rolling_var = pd.Series(dt).rolling(20, min_periods=3).var(ddof=0).dropna()
        burst_thr = float(np.quantile(dt, 0.05))
        burstiness = float(np.mean(dt < burst_thr))
        periodicity = float(np.clip(1.0 - jitter, 0.0, 1.0))
        profiles[int(can_id)] = {
            "count": float(len(g)),
            "mean_frequency_hz": mean_freq,
            "mean_period_ms": mean_period * 1000.0,
            "period_std_ms": std_period * 1000.0,
            "jitter_ratio": jitter,
            "mean_payload_entropy": ent,
            "payload_entropy_std": float(np.std(ents) if ents else 0.0),
            "mean_byte_change_rate": float(np.mean(byte_change_rate) if byte_change_rate else 0.0),
            "payload_repetition_ratio": repetition_ratio,
            "burstiness": burstiness,
            "periodicity": periodicity,
            "payload_stability": float(1.0 - np.mean(byte_change_rate) if byte_change_rate else 1.0),
            "mean_hamming_distance": float(np.mean(hd) if hd else 0.0),
            "rolling_dt_var_mean": float(rolling_var.mean() if len(rolling_var) else 0.0),
            "dominance_ratio": float(len(g) / max(len(df), 1)),
            "active_ratio": float((ts[-1] - ts[0]) / total_duration) if len(ts) > 1 else 0.0,
        }
    return profiles


def score_timing_anomalies(df: pd.DataFrame, profiles: dict[int, dict[str, float]]) -> pd.DataFrame:
    out_rows = []
    for can_id, g in df.groupby("can_id", sort=False):
        cid = int(can_id)
        if cid not in profiles:
            continue
        base = profiles[cid]
        g = g.sort_values("timestamp").reset_index(drop=True)
        ts = g["timestamp"].to_numpy(dtype=np.float64)
        dt = np.diff(ts, prepend=ts[0])
        mean_p = max(base["mean_period_ms"] / 1000.0, 1e-6)
        std_p = max(base["period_std_ms"] / 1000.0, 1e-6)
        for i in range(1, len(g)):
            cur_dt = max(float(dt[i]), 1e-9)
            # Step 6.1 standalone timing components
            freq_dev = abs(cur_dt - mean_p) / std_p
            burst_score = max(0.0, (mean_p - cur_dt) / mean_p)
            silence_score = max(0.0, (cur_dt - (mean_p + 3.0 * std_p)) / max(mean_p, 1e-6))
            # jitter anomaly from rolling window
            w0 = max(1, i - 20)
            local_dt = np.diff(ts[w0 : i + 1])
            local_jitter = float(np.std(local_dt) / max(np.mean(local_dt), 1e-9)) if len(local_dt) > 1 else 0.0
            jitter_anom = max(0.0, local_jitter - base["jitter_ratio"])
            arb_dom = max(0.0, (1.0 / (cid + 1.0)) * burst_score)  # lower ID + burst -> more suspicious
            timing_score = freq_dev + burst_score + silence_score + jitter_anom + arb_dom
            out_rows.append(
                {
                    "timestamp": float(ts[i]),
                    "can_id": cid,
                    "timing_score": float(timing_score),
                    "burst_score": float(burst_score),
                    "silence_score": float(silence_score),
                    "frequency_dev_score": float(freq_dev),
                    "jitter_score": float(jitter_anom),
                    "arbitration_dom_score": float(arb_dom),
                }
            )
    return pd.DataFrame(out_rows)


def make_profile_plots(df: pd.DataFrame, profiles: dict[int, dict[str, float]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    top_ids = sorted(profiles.items(), key=lambda kv: kv[1]["count"], reverse=True)[:TOP_N_IDS]
    for cid, _ in top_ids:
        g = df[df["can_id"] == cid].sort_values("timestamp")
        ts = g["timestamp"].to_numpy(dtype=np.float64)
        if len(ts) < 4:
            continue
        dt = np.diff(ts)
        payloads = [bytes(int(v) for v in row) for row in g[BYTE_COLS].to_numpy(dtype=np.uint8)]
        rep = pd.Series([p.hex() for p in payloads]).value_counts(normalize=True).head(20)
        ents = []
        win = 32
        for i in range(0, len(payloads), max(1, win // 2)):
            chunk = payloads[i : i + win]
            if len(chunk) >= 4:
                ents.append(payload_entropy(chunk))
        fig, ax = plt.subplots(2, 2, figsize=(11, 8))
        ax[0, 0].hist(dt * 1000.0, bins=40, color="#2563eb", alpha=0.8)
        ax[0, 0].set_title(f"ID 0x{cid:X} Inter-arrival ms")
        ax[0, 1].hist(ents, bins=30, color="#059669", alpha=0.8)
        ax[0, 1].set_title("Rolling payload entropy")
        ax[1, 0].plot(np.clip(dt, 0, np.quantile(dt, 0.99)) * 1000.0, color="#dc2626", linewidth=1.0)
        ax[1, 0].set_title("Burst behavior (clipped dt ms)")
        ax[1, 1].bar(range(len(rep)), rep.to_numpy(), color="#7c3aed")
        ax[1, 1].set_title("Payload repetition (top patterns)")
        fig.tight_layout()
        fig.savefig(out_dir / f"profile_id_{cid:X}.png", dpi=130)
        plt.close(fig)


def summarize_tesla_priors(tesla_df: pd.DataFrame, categories: dict[str, list[int]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for cat, ids in categories.items():
        g = tesla_df[tesla_df["can_id"].isin(ids)].copy()
        if g.empty:
            continue
        g = g.sort_values(["can_id", "timestamp"])
        deltas = g.groupby("can_id")["timestamp"].diff().dropna()
        deltas = deltas[deltas > 0]
        if len(deltas) == 0:
            continue
        out[cat] = {
            "avg_period_ms": float(deltas.mean() * 1000.0),
            "p50_period_ms": float(np.quantile(deltas, 0.5) * 1000.0),
            "p95_period_ms": float(np.quantile(deltas, 0.95) * 1000.0),
            "jitter_ratio": float(deltas.std() / max(deltas.mean(), 1e-9)),
            "burst_ratio_p05": float(np.mean(deltas < np.quantile(deltas, 0.05))),
            "silence_ratio_p95": float(np.mean(deltas > np.quantile(deltas, 0.95))),
            "stability_index": float(np.clip(1.0 - (deltas.std() / max(deltas.mean(), 1e-9)), 0.0, 1.0)),
            "message_count": float(len(g)),
        }
    return out


def print_phase4_analysis(tesla_df: pd.DataFrame, categories: dict[str, list[int]], priors: dict[str, dict[str, float]]) -> None:
    print("\n=== PHASE 4.1 / 4.2 / 4.3: TESLA-DERIVED GENERIC PRIORS ===")
    print("Category coverage (message IDs):")
    for k, v in categories.items():
        print(f"  - {k}: {len(v)} IDs")
    print("\nTemporal + dynamics priors (no Kaggle semantic mapping):")
    for cat, stats in priors.items():
        print(
            f"  - {cat}: avg_period={stats['avg_period_ms']:.3f}ms p95={stats['p95_period_ms']:.3f}ms "
            f"jitter={stats['jitter_ratio']:.4f} stability={stats['stability_index']:.4f}"
        )
    by_id = tesla_df["can_id"].value_counts()
    print("\nFastest/Heavy recurring IDs (Tesla log observation):")
    for cid, cnt in by_id.head(12).items():
        g = tesla_df[tesla_df["can_id"] == cid].sort_values("timestamp")
        dt = g["timestamp"].diff().dropna()
        if len(dt):
            print(f"  - 0x{int(cid):X}: count={int(cnt)} mean_period_ms={float(dt.mean()*1000.0):.3f}")


def print_phase5_summary(profiles: dict[int, dict[str, float]]) -> None:
    print("\n=== PHASE 5.1: KAGGLE NORMAL PER-ID PROFILES ===")
    print(f"Profiled CAN IDs: {len(profiles)}")
    top = sorted(profiles.items(), key=lambda kv: kv[1]["count"], reverse=True)[:12]
    for cid, p in top:
        print(
            f"  - 0x{cid:X}: freq={p['mean_frequency_hz']:.2f}Hz period={p['mean_period_ms']:.3f}ms "
            f"jitter={p['jitter_ratio']:.4f} entropy={p['mean_payload_entropy']:.3f} rep={p['payload_repetition_ratio']:.3f}"
        )


def print_phase6_summary(scores_by_set: dict[str, pd.DataFrame]) -> None:
    print("\n=== PHASE 6.2: TIMING SCORE DISTRIBUTIONS (SEPARATE FROM ML) ===")
    for name, sdf in scores_by_set.items():
        if sdf.empty:
            print(f"  - {name}: no timing scores")
            continue
        q = sdf["timing_score"].quantile([0.5, 0.9, 0.95, 0.99]).to_dict()
        print(
            f"  - {name}: n={len(sdf)} p50={q[0.5]:.4f} p90={q[0.9]:.4f} "
            f"p95={q[0.95]:.4f} p99={q[0.99]:.4f}"
        )


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    plot_dir = args.out / "profile_plots"
    score_dir = args.out / "timing_score_plots"
    score_dir.mkdir(parents=True, exist_ok=True)

    # Phase 4: Tesla-derived generic behavior priors
    categories = parse_tesla_dbc_categories(args.tesla_dbc)
    tesla_df = parse_tesla_log(args.tesla_log)
    priors = summarize_tesla_priors(tesla_df, categories) if not tesla_df.empty else {}
    print_phase4_analysis(tesla_df, categories, priors)

    # Phase 5: Kaggle normal-only per-ID profiles
    normal_df = load_kaggle_dataset(args.normal)
    normal_df["can_id"] = pd.to_numeric(normal_df["can_id"], errors="coerce").astype("Int64")
    normal_df = normal_df.dropna(subset=["can_id"]).copy()
    normal_df["can_id"] = normal_df["can_id"].astype(int)
    profiles = build_per_id_profiles(normal_df)
    print_phase5_summary(profiles)
    make_profile_plots(normal_df, profiles, plot_dir)

    # Phase 6: timing anomaly scores (no fusion)
    scores_by_set: dict[str, pd.DataFrame] = {}
    normal_scores = score_timing_anomalies(normal_df, profiles)
    scores_by_set["normal"] = normal_scores
    for attack, fname in ATTACK_FILES.items():
        p = args.archive / fname
        if not p.exists():
            scores_by_set[attack] = pd.DataFrame()
            continue
        atk_raw = load_attack_raw(p)
        atk_raw["can_id"] = atk_raw["can_id"].astype(int)
        atk_scores = score_timing_anomalies(atk_raw, profiles)
        scores_by_set[attack] = atk_scores
    print_phase6_summary(scores_by_set)

    # Distribution plots
    for name, sdf in scores_by_set.items():
        if sdf.empty:
            continue
        plt.figure(figsize=(9, 5))
        plt.hist(sdf["timing_score"], bins=80, density=True, alpha=0.85, color="#2563eb")
        plt.title(f"Timing Score Distribution - {name}")
        plt.xlabel("timing_score")
        plt.ylabel("density")
        plt.tight_layout()
        plt.savefig(score_dir / f"timing_score_dist_{name}.png", dpi=140)
        plt.close()

    for attack in ATTACK_FILES:
        if scores_by_set["normal"].empty or scores_by_set[attack].empty:
            continue
        plt.figure(figsize=(9, 5))
        plt.hist(scores_by_set["normal"]["timing_score"], bins=100, density=True, alpha=0.45, label="normal")
        plt.hist(scores_by_set[attack]["timing_score"], bins=100, density=True, alpha=0.45, label=attack)
        plt.title(f"Timing Score: normal vs {attack}")
        plt.xlabel("timing_score")
        plt.ylabel("density")
        plt.legend()
        plt.tight_layout()
        plt.savefig(score_dir / f"timing_score_normal_vs_{attack}.png", dpi=140)
        plt.close()

    # Save artifacts
    (args.out / "tesla_generic_priors.json").write_text(json.dumps(priors, indent=2), encoding="utf-8")
    profiles_json = {f"0x{k:X}": v for k, v in profiles.items()}
    (args.out / "kaggle_normal_id_profiles.json").write_text(json.dumps(profiles_json, indent=2), encoding="utf-8")
    for name, sdf in scores_by_set.items():
        if not sdf.empty:
            sdf.to_csv(args.out / f"timing_scores_{name}.csv", index=False)

    print(f"\nSaved outputs under: {args.out}")


if __name__ == "__main__":
    main()
