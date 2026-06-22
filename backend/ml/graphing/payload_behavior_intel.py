from __future__ import annotations

import argparse
import gc
import json
import time
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
OUT_ROOT = ASSETS_ROOT / "evaluation" / "payload_behavior"

ATTACK_FILES = {
    "DoS": "DoS_dataset.csv",
    "Fuzzy": "Fuzzy_dataset.csv",
    "RPM": "RPM_dataset.csv",
    "gear": "gear_dataset.csv",
}

BYTE_COLS = [f"b{i}" for i in range(8)]
TOP_N_IDS = 20
ROLL_WIN = 32
ENABLE_PLOTS = False
TOP_K_IDS = 5
DEBUG_SAMPLE_SIZE = 100000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--normal", type=Path, default=ARCHIVE_ROOT / "normal_run_data.txt")
    p.add_argument("--archive", type=Path, default=ARCHIVE_ROOT)
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


def _payload_to_tuple(p: bytes) -> tuple[int, ...]:
    return tuple(int(x) for x in p)


def _rolling_entropy(payloads: list[bytes], window: int = ROLL_WIN) -> np.ndarray:
    out = np.zeros(len(payloads), dtype=np.float64)
    for i in range(len(payloads)):
        lo = max(0, i - window + 1)
        chunk = payloads[lo : i + 1]
        out[i] = payload_entropy(chunk)
    return out


def _log_stage(stage_idx: int, total: int, msg: str, t0: float, df: pd.DataFrame | None = None) -> None:
    elapsed = time.perf_counter() - t0
    if df is not None:
        active_ids = int(df["can_id"].nunique()) if "can_id" in df.columns and not df.empty else 0
        print(f"[{stage_idx}/{total}] {msg} | elapsed={elapsed:.2f}s | rows={len(df):,} | cols={df.shape[1]} | active_can_ids={active_ids}")
    else:
        print(f"[{stage_idx}/{total}] {msg} | elapsed={elapsed:.2f}s")


def _sequence_transition_consistency(payloads: list[bytes]) -> tuple[float, dict[tuple[tuple[int, ...], tuple[int, ...]], int]]:
    if len(payloads) < 3:
        return 1.0, {}
    transitions: dict[tuple[tuple[int, ...], tuple[int, ...]], int] = defaultdict(int)
    for i in range(1, len(payloads)):
        key = (_payload_to_tuple(payloads[i - 1]), _payload_to_tuple(payloads[i]))
        transitions[key] += 1
    probs = np.array(list(transitions.values()), dtype=np.float64)
    probs /= probs.sum()
    # lower entropy over transition motifs -> more consistent dynamics
    ent = float(-(probs * np.log2(probs + 1e-12)).sum())
    max_ent = math_log2_safe(len(probs))
    consistency = 1.0 - (ent / max(max_ent, 1e-9))
    return float(np.clip(consistency, 0.0, 1.0)), transitions


def math_log2_safe(x: int) -> float:
    return float(np.log2(max(x, 1)))


def build_payload_profiles(normal_df: pd.DataFrame) -> dict[int, dict[str, float]]:
    profiles: dict[int, dict[str, float]] = {}
    for can_id, g in normal_df.groupby("can_id", sort=False):
        g = g.sort_values("timestamp").reset_index(drop=True)
        byte_arr = g[BYTE_COLS].to_numpy(dtype=np.int16, copy=False)
        payloads = [bytes(row.astype(np.uint8)) for row in byte_arr]
        if len(payloads) < 4:
            continue
        diffs = np.diff(byte_arr, axis=0)
        adiffs = np.abs(diffs)
        hd = np.unpackbits(adiffs.astype(np.uint8), axis=1).sum(axis=1).astype(np.float64)
        delta_mag = adiffs.mean(axis=1).astype(np.float64)
        byte_smooth = (1.0 / (1.0 + adiffs)).mean(axis=1).astype(np.float64)
        d1 = diffs[:-1]
        d2 = diffs[1:]
        sign_flips = ((d1 != 0) & (d2 != 0) & (np.sign(d1) != np.sign(d2))).sum(axis=1)
        oscillations = int((sign_flips >= 4).sum())
        motif_seq = [(_payload_to_tuple(payloads[i - 1]), _payload_to_tuple(payloads[i])) for i in range(1, len(payloads))]
        roll_hd = pd.Series(hd).rolling(ROLL_WIN, min_periods=4)
        roll_delta = pd.Series(delta_mag).rolling(ROLL_WIN, min_periods=4)
        ent_series = _rolling_entropy(payloads, window=ROLL_WIN)
        ent_shift = np.abs(np.diff(ent_series))
        consistency, transitions = _sequence_transition_consistency(payloads)
        transition_counts = pd.Series([f"{a}->{b}" for a, b in motif_seq]).value_counts(normalize=True)
        repetition_ratio = float(pd.Series([p.hex() for p in payloads]).value_counts(normalize=True).iloc[0])
        profiles[int(can_id)] = {
            "count": float(len(payloads)),
            "mean_hamming": float(np.mean(hd)),
            "hamming_std": float(np.std(hd)),
            "mean_payload_delta": float(np.mean(delta_mag)),
            "payload_delta_std": float(np.std(delta_mag)),
            "payload_delta_var": float(np.var(delta_mag)),
            "rolling_hamming_mean": float(roll_hd.mean().mean()) if not roll_hd.mean().empty else float(np.mean(hd)),
            "rolling_hamming_std": float(roll_hd.std().mean()) if not roll_hd.std().empty else float(np.std(hd)),
            "rolling_delta_var_mean": float(roll_delta.var().mean()) if not roll_delta.var().empty else float(np.var(delta_mag)),
            "byte_transition_smoothness": float(np.mean(byte_smooth)),
            "abrupt_jump_p99": float(np.quantile(delta_mag, 0.99)),
            "transition_consistency": float(consistency),
            "oscillation_ratio": float(oscillations / max(len(payloads) - 2, 1)),
            "repetition_collapse_ratio": repetition_ratio,
            "entropy_mean": float(np.mean(ent_series)),
            "entropy_std": float(np.std(ent_series)),
            "entropy_shift_mean": float(np.mean(ent_shift) if len(ent_shift) else 0.0),
            "entropy_shift_std": float(np.std(ent_shift) if len(ent_shift) else 0.0),
            "entropy_instability": float(np.var(ent_shift) if len(ent_shift) else 0.0),
            "top_transition_ratio": float(transition_counts.iloc[0]) if len(transition_counts) else 0.0,
        }
    return profiles


def score_payload_behavior(df: pd.DataFrame, profiles: dict[int, dict[str, float]]) -> pd.DataFrame:
    rows = []
    top_ids = {cid for cid, _ in sorted(profiles.items(), key=lambda kv: kv[1]["count"], reverse=True)[:TOP_K_IDS]}
    for can_id, g in df.groupby("can_id", sort=False):
        cid = int(can_id)
        if cid not in top_ids:
            continue
        if cid not in profiles:
            continue
        base = profiles[cid]
        g = g.sort_values("timestamp").reset_index(drop=True)
        byte_arr = g[BYTE_COLS].to_numpy(dtype=np.int16, copy=False)
        payloads = [bytes(row.astype(np.uint8)) for row in byte_arr]
        if len(payloads) < 3:
            continue
        t_entropy = time.perf_counter()
        ent_series = _rolling_entropy(payloads, window=ROLL_WIN)
        print(f"START rolling entropy for ID 0x{cid:X}... DONE in {time.perf_counter()-t_entropy:.2f}s")
        t_hamming = time.perf_counter()
        diffs = np.diff(byte_arr, axis=0)
        adiffs = np.abs(diffs)
        hds = np.unpackbits(adiffs.astype(np.uint8), axis=1).sum(axis=1).astype(np.float64)
        dmag_all = adiffs.mean(axis=1).astype(np.float64)
        smooth_all = (1.0 / (1.0 + adiffs)).mean(axis=1).astype(np.float64)
        print(f"START rolling hamming for ID 0x{cid:X}... DONE in {time.perf_counter()-t_hamming:.2f}s")
        motif_counts: dict[tuple[tuple[int, ...], tuple[int, ...]], int] = defaultdict(int)
        for i in range(1, len(payloads)):
            p0, p1 = payloads[i - 1], payloads[i]
            hd = float(hds[i - 1])
            dmag = float(dmag_all[i - 1])
            smooth = float(smooth_all[i - 1])
            abrupt = max(0.0, (dmag - base["abrupt_jump_p99"]) / max(base["abrupt_jump_p99"], 1e-6))
            # entropy behavior
            ent_cur = float(ent_series[i])
            ent_prev = float(ent_series[i - 1])
            ent_shift = abs(ent_cur - ent_prev)
            ent_shift_anom = abs(ent_shift - base["entropy_shift_mean"]) / max(base["entropy_shift_std"], 1e-6)
            ent_level_anom = abs(ent_cur - base["entropy_mean"]) / max(base["entropy_std"], 1e-6)
            # continuity
            h_anom = abs(hd - base["mean_hamming"]) / max(base["hamming_std"], 1e-6)
            d_anom = abs(dmag - base["mean_payload_delta"]) / max(base["payload_delta_std"], 1e-6)
            smooth_anom = max(0.0, (base["byte_transition_smoothness"] - smooth) / max(base["byte_transition_smoothness"], 1e-6))
            # transition realism
            key = (_payload_to_tuple(p0), _payload_to_tuple(p1))
            motif_counts[key] += 1
            motif_prob = motif_counts[key] / max(i, 1)
            transition_anom = max(0.0, (base["top_transition_ratio"] - motif_prob))
            # oscillation detection in local 3-step context
            osc_anom = 0.0
            if i >= 2:
                p_1 = payloads[i - 2]
                sign_flips = 0
                for a, b, c in zip(p_1, p0, p1):
                    s1 = int(b) - int(a)
                    s2 = int(c) - int(b)
                    if s1 != 0 and s2 != 0 and np.sign(s1) != np.sign(s2):
                        sign_flips += 1
                osc_ratio = sign_flips / 8.0
                osc_anom = max(0.0, osc_ratio - base["oscillation_ratio"])
            # repetition-collapse
            rep_window = payloads[max(0, i - ROLL_WIN + 1) : i + 1]
            rep_ratio = float(pd.Series([p.hex() for p in rep_window]).value_counts(normalize=True).iloc[0])
            rep_anom = max(0.0, rep_ratio - base["repetition_collapse_ratio"])

            continuity_score = h_anom + d_anom + smooth_anom + abrupt
            entropy_score = ent_shift_anom + ent_level_anom
            transition_score = transition_anom + rep_anom
            oscillation_score = osc_anom
            payload_behavior_score = continuity_score + entropy_score + transition_score + oscillation_score

            rows.append(
                {
                    "timestamp": float(g.loc[i, "timestamp"]),
                    "can_id": cid,
                    "payload_behavior_score": float(payload_behavior_score),
                    "continuity_score": float(continuity_score),
                    "entropy_score": float(entropy_score),
                    "transition_score": float(transition_score),
                    "oscillation_score": float(oscillation_score),
                    "hamming": hd,
                    "payload_delta": dmag,
                    "entropy_shift": float(ent_shift),
                }
            )
    return pd.DataFrame(rows)


def make_profile_plots(df: pd.DataFrame, profiles: dict[int, dict[str, float]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    top_ids = sorted(profiles.items(), key=lambda kv: kv[1]["count"], reverse=True)[:TOP_N_IDS]
    for cid, _ in top_ids:
        g = df[df["can_id"] == cid].sort_values("timestamp")
        payloads = [bytes(int(v) for v in row) for row in g[BYTE_COLS].to_numpy(dtype=np.uint8)]
        if len(payloads) < 4:
            continue
        hd = [hamming_distance(payloads[i - 1], payloads[i]) for i in range(1, len(payloads))]
        dmag = [float(np.mean([abs(int(a) - int(b)) for a, b in zip(payloads[i], payloads[i - 1])])) for i in range(1, len(payloads))]
        ents = _rolling_entropy(payloads, window=ROLL_WIN)
        shifts = np.abs(np.diff(ents))
        fig, ax = plt.subplots(2, 2, figsize=(11, 8))
        ax[0, 0].hist(hd, bins=40, color="#2563eb", alpha=0.8)
        ax[0, 0].set_title(f"ID 0x{cid:X} rolling Hamming")
        ax[0, 1].hist(dmag, bins=40, color="#059669", alpha=0.8)
        ax[0, 1].set_title("Payload derivative magnitude")
        ax[1, 0].hist(shifts, bins=40, color="#dc2626", alpha=0.8)
        ax[1, 0].set_title("Entropy shift distribution")
        ax[1, 1].plot(np.clip(dmag, 0, np.quantile(dmag, 0.99)), color="#7c3aed", linewidth=1.0)
        ax[1, 1].set_title("Abrupt jump trace (clipped)")
        fig.tight_layout()
        fig.savefig(out_dir / f"payload_profile_id_{cid:X}.png", dpi=130)
        plt.close(fig)


def print_profile_summary(profiles: dict[int, dict[str, float]]) -> None:
    print("\n=== PHASE 7.1D: PAYLOAD STABILITY PROFILES (NORMAL ONLY) ===")
    print(f"Profiled CAN IDs: {len(profiles)}")
    top = sorted(profiles.items(), key=lambda kv: kv[1]["count"], reverse=True)[:12]
    for cid, p in top:
        print(
            f"  - 0x{cid:X}: h_mean={p['mean_hamming']:.3f} h_std={p['hamming_std']:.3f} "
            f"d_mean={p['mean_payload_delta']:.3f} d_std={p['payload_delta_std']:.3f} "
            f"ent_shift_mean={p['entropy_shift_mean']:.4f} trans_cons={p['transition_consistency']:.3f} "
            f"osc={p['oscillation_ratio']:.3f}"
        )


def print_distribution_summary(scores_by_set: dict[str, pd.DataFrame]) -> None:
    print("\n=== PHASE 7.3: PAYLOAD SCORE DISTRIBUTIONS (SEPARATE) ===")
    for name, sdf in scores_by_set.items():
        if sdf.empty:
            print(f"  - {name}: no scores")
            continue
        q = sdf["payload_behavior_score"].quantile([0.5, 0.9, 0.95, 0.99]).to_dict()
        print(
            f"  - {name}: n={len(sdf)} p50={q[0.5]:.4f} p90={q[0.9]:.4f} "
            f"p95={q[0.95]:.4f} p99={q[0.99]:.4f}"
        )


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    profile_plot_dir = args.out / "profile_plots"
    score_plot_dir = args.out / "payload_score_plots"
    rolling_plot_dir = args.out / "rolling_anomaly_plots"
    if ENABLE_PLOTS:
        score_plot_dir.mkdir(parents=True, exist_ok=True)
        rolling_plot_dir.mkdir(parents=True, exist_ok=True)
    total_stages = 8
    pipeline_t0 = time.perf_counter()

    # Normal baseline only
    _log_stage(1, total_stages, "Loading dataset...", pipeline_t0)
    normal_df = load_kaggle_dataset(args.normal)
    normal_df["can_id"] = pd.to_numeric(normal_df["can_id"], errors="coerce").astype("Int64")
    normal_df = normal_df.dropna(subset=["can_id"]).copy()
    normal_df["can_id"] = normal_df["can_id"].astype(int)
    if DEBUG_SAMPLE_SIZE and len(normal_df) > DEBUG_SAMPLE_SIZE:
        normal_df = normal_df.sort_values("timestamp").head(DEBUG_SAMPLE_SIZE).copy()
    _log_stage(1, total_stages, "Loading dataset done", pipeline_t0, normal_df)

    # 7.1 profiles
    _log_stage(2, total_stages, "Building normal-only payload profiles...", pipeline_t0, normal_df)
    profiles = build_payload_profiles(normal_df)
    print_profile_summary(profiles)
    if ENABLE_PLOTS:
        make_profile_plots(normal_df, profiles, profile_plot_dir)
    gc.collect()

    # 7.2/7.3 payload behavior scores
    _log_stage(5, total_stages, "Scoring payload anomalies...", pipeline_t0)
    scores_by_set: dict[str, pd.DataFrame] = {}
    normal_scores = score_payload_behavior(normal_df, profiles)
    scores_by_set["normal"] = normal_scores
    for attack, fname in ATTACK_FILES.items():
        p = args.archive / fname
        if not p.exists():
            scores_by_set[attack] = pd.DataFrame()
            continue
        atk = load_attack_raw(p)
        atk["can_id"] = atk["can_id"].astype(int)
        if DEBUG_SAMPLE_SIZE and len(atk) > DEBUG_SAMPLE_SIZE:
            atk = atk.sort_values("timestamp").head(DEBUG_SAMPLE_SIZE).copy()
        scores_by_set[attack] = score_payload_behavior(atk, profiles)
        gc.collect()

    _log_stage(6, total_stages, "Generating distributions...", pipeline_t0)
    print_distribution_summary(scores_by_set)

    # Distribution plots
    if ENABLE_PLOTS:
        _log_stage(7, total_stages, "Generating plots...", pipeline_t0)

        for name, sdf in scores_by_set.items():
            if sdf.empty:
                continue
            plt.figure(figsize=(9, 5))
            plt.hist(sdf["payload_behavior_score"], bins=100, density=True, alpha=0.85, color="#2563eb")
            plt.title(f"Payload Behavior Score Distribution - {name}")
            plt.tight_layout()
            plt.savefig(score_plot_dir / f"payload_score_dist_{name}.png", dpi=140)
            plt.close()

    # Save outputs
    _log_stage(8, total_stages, "Saving outputs...", pipeline_t0)
    profiles_json = {f"0x{k:X}": v for k, v in profiles.items()}
    (args.out / "kaggle_normal_payload_profiles.json").write_text(json.dumps(profiles_json, indent=2), encoding="utf-8")
    for name, sdf in scores_by_set.items():
        if not sdf.empty:
            sdf.to_csv(args.out / f"payload_scores_{name}.csv", index=False)

    print(f"\nSaved outputs under: {args.out}")
    print(f"[DONE] total_elapsed={time.perf_counter()-pipeline_t0:.2f}s | enable_plots={ENABLE_PLOTS} | top_k_ids={TOP_K_IDS} | debug_sample_size={DEBUG_SAMPLE_SIZE}")


if __name__ == "__main__":
    main()
