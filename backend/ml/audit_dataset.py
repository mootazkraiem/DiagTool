"""
Dataset Audit Script for CAN Bus Anomaly Detection

This script performs a comprehensive audit of the processed anomaly dataset to validate
whether anomalies are truly learnable and separable from normal traffic.

Usage:
    python backend/ml/audit_dataset.py

Assumptions:
- Processed dataframe contains: timestamp, can_id, state, vehicle, label (0=normal, 1=anomaly)
- Engineered features: time_diff, rolling_std_time_diff, byte_diff, etc.
- Optional raw byte columns: b0, b1, ..., b7

Output:
- CSV samples: backend/ml/audit/audit_normal.csv, audit_anomaly.csv
- Report: backend/ml/audit/audit_report.txt
- Plots: backend/ml/audit/plots/
- Final health score: GOOD, QUESTIONABLE, WEAK
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from scipy.stats import ks_2samp

try:
    from sklearn.manifold import TSNE
    TSNE_AVAILABLE = True
except ImportError:
    TSNE_AVAILABLE = False

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
AUDIT_DIR = Path(__file__).resolve().parents[2] / "backend" / "ml" / "audit"
PLOTS_DIR = AUDIT_DIR / "plots"
NORMAL_SAMPLE_SIZE = 100
ANOMALY_SAMPLE_SIZE = 100
FEATURE_COLS = [
    "time_diff", "rolling_std_time_diff", "rolling_mean_byte_diff",
    "rolling_byte_diff_std", "rolling_max_byte_diff", "rolling_min_byte_diff",
    "rolling_range_byte_diff", "msg_frequency", "byte_diff", "changed_bytes_count"
]
BYTE_COLS = [f"b{i}" for i in range(8)]

def load_processed_dataset() -> pd.DataFrame:
    """Load and preprocess the dataset for audit."""
    from backend.ml.feature_engineering import load_kaggle_dataset, preprocess_pipeline

    kaggle_path = Path(__file__).resolve().parents[2] / "assets" / "archive" / "normal_run_data.txt"
    if not kaggle_path.exists():
        raise FileNotFoundError(f"Kaggle dataset not found: {kaggle_path}")

    raw_df = load_kaggle_dataset(str(kaggle_path))
    feat_df, _, _ = preprocess_pipeline(raw_df, scaler=None, fit=True)

    # Add dummy labels for audit - in real scenario, load labeled data
    # For now, assume all are normal, or add synthetic anomalies
    feat_df['label'] = 0  # Normal
    # Add some synthetic anomalies
    anomaly_indices = np.random.choice(feat_df.index, size=int(0.1 * len(feat_df)), replace=False)
    feat_df.loc[anomaly_indices, 'label'] = 1

    feat_df['vehicle'] = 'kaggle_normal'
    feat_df['state'] = 'unknown'  # Would be set by pipeline

    return feat_df

def sample_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Randomly sample 100 normal and 100 anomaly rows."""
    normal_df = df[df['label'] == 0].sample(n=min(NORMAL_SAMPLE_SIZE, len(df[df['label'] == 0])), random_state=42)
    anomaly_df = df[df['label'] == 1].sample(n=min(ANOMALY_SAMPLE_SIZE, len(df[df['label'] == 1])), random_state=42)
    return normal_df, anomaly_df

def save_samples(normal_df: pd.DataFrame, anomaly_df: pd.DataFrame):
    """Save sampled data to CSV."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    normal_df.to_csv(AUDIT_DIR / "audit_normal.csv", index=False)
    anomaly_df.to_csv(AUDIT_DIR / "audit_anomaly.csv", index=False)
    logger.info("Saved sample CSVs to %s", AUDIT_DIR)

def statistical_audit(normal_df: pd.DataFrame, anomaly_df: pd.DataFrame) -> Dict:
    """Compute statistical summaries and separability metrics."""
    results = {}
    for feature in FEATURE_COLS:
        if feature not in normal_df.columns or feature not in anomaly_df.columns:
            continue
        normal_vals = normal_df[feature].dropna()
        anomaly_vals = anomaly_df[feature].dropna()

        normal_stats = {
            'mean': normal_vals.mean(),
            'std': normal_vals.std(),
            'median': normal_vals.median(),
            'min': normal_vals.min(),
            'max': normal_vals.max()
        }
        anomaly_stats = {
            'mean': anomaly_vals.mean(),
            'std': anomaly_vals.std(),
            'median': anomaly_vals.median(),
            'min': anomaly_vals.min(),
            'max': anomaly_vals.max()
        }

        # Cohen's d
        pooled_std = np.sqrt((normal_stats['std']**2 + anomaly_stats['std']**2) / 2)
        cohens_d = abs(normal_stats['mean'] - anomaly_stats['mean']) / (pooled_std + 1e-6)

        # KS statistic
        ks_stat, _ = ks_2samp(normal_vals, anomaly_vals)

        # Overlap estimate (simplified)
        overlap = 1 - abs(normal_stats['mean'] - anomaly_stats['mean']) / (normal_stats['std'] + anomaly_stats['std'] + 1e-6)

        results[feature] = {
            'normal': normal_stats,
            'anomaly': anomaly_stats,
            'cohens_d': cohens_d,
            'ks_stat': ks_stat,
            'overlap': overlap
        }

    # Rank by separability (higher cohens_d and ks_stat better)
    ranked = sorted(results.items(), key=lambda x: (x[1]['cohens_d'], x[1]['ks_stat']), reverse=True)
    results['ranking'] = ranked

    return results

def nearest_neighbor_purity(normal_df: pd.DataFrame, anomaly_df: pd.DataFrame) -> Dict:
    """Compute nearest-neighbor purity for anomalies."""
    combined = pd.concat([normal_df, anomaly_df])
    features = [f for f in FEATURE_COLS if f in combined.columns]
    if not features:
        return {}

    X = combined[features].fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    nn = NearestNeighbors(n_neighbors=6)  # 5 + self
    nn.fit(X_scaled)

    anomaly_indices = combined[combined['label'] == 1].index
    anomaly_purities = []
    for idx in anomaly_indices:
        distances, indices = nn.kneighbors([X_scaled[combined.index.get_loc(idx)]])
        neighbors = combined.iloc[indices[0][1:]]  # exclude self
        purity = (neighbors['label'] == 1).mean()
        anomaly_purities.append(purity)

    normal_indices = combined[combined['label'] == 0].index
    normal_purities = []
    for idx in normal_indices[:len(anomaly_indices)]:  # balance
        distances, indices = nn.kneighbors([X_scaled[combined.index.get_loc(idx)]])
        neighbors = combined.iloc[indices[0][1:]]
        purity = (neighbors['label'] == 0).mean()
        normal_purities.append(purity)

    return {
        'anomaly_purity': np.mean(anomaly_purities),
        'normal_purity': np.mean(normal_purities)
    }

def supervised_sanity_test(normal_df: pd.DataFrame, anomaly_df: pd.DataFrame) -> Dict:
    """Train supervised classifiers and evaluate."""
    combined = pd.concat([normal_df, anomaly_df])
    features = [f for f in FEATURE_COLS if f in combined.columns]
    if not features:
        return {}

    X = combined[features].fillna(0)
    y = combined['label']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    results = {}

    # RandomForest
    rf = RandomForestClassifier(n_estimators=100, random_state=42)
    rf.fit(X_train, y_train)
    y_pred = rf.predict(X_test)
    y_proba = rf.predict_proba(X_test)[:, 1]
    results['random_forest'] = {
        'accuracy': accuracy_score(y_test, y_pred),
        'f1': f1_score(y_test, y_pred),
        'precision': precision_score(y_test, y_pred),
        'recall': recall_score(y_test, y_pred),
        'roc_auc': roc_auc_score(y_test, y_proba)
    }

    # XGBoost if available
    if XGB_AVAILABLE:
        xgb_clf = xgb.XGBClassifier(n_estimators=100, random_state=42)
        xgb_clf.fit(X_train, y_train)
        y_pred = xgb_clf.predict(X_test)
        y_proba = xgb_clf.predict_proba(X_test)[:, 1]
        results['xgboost'] = {
            'accuracy': accuracy_score(y_test, y_pred),
            'f1': f1_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred),
            'recall': recall_score(y_test, y_pred),
            'roc_auc': roc_auc_score(y_test, y_proba)
        }

    return results

def temporal_analysis(normal_df: pd.DataFrame, anomaly_df: pd.DataFrame) -> Dict:
    """Analyze temporal behavior."""
    results = {}

    for label, df in [('normal', normal_df), ('anomaly', anomaly_df)]:
        if 'timestamp' in df.columns:
            time_diffs = df['timestamp'].diff().dropna()
            results[f'{label}_time_variance'] = time_diffs.var()
            results[f'{label}_time_mean'] = time_diffs.mean()

        if 'can_id' in df.columns:
            can_freq = df['can_id'].value_counts()
            results[f'{label}_unique_can_ids'] = len(can_freq)
            results[f'{label}_can_id_entropy'] = -sum((can_freq / len(df)) * np.log(can_freq / len(df) + 1e-6))

    return results

def raw_byte_analysis(normal_df: pd.DataFrame, anomaly_df: pd.DataFrame) -> Dict:
    """Analyze raw bytes if available."""
    results = {}
    byte_cols_present = [col for col in BYTE_COLS if col in normal_df.columns and col in anomaly_df.columns]

    if not byte_cols_present:
        return results

    for label, df in [('normal', normal_df), ('anomaly', anomaly_df)]:
        byte_matrix = df[byte_cols_present].values
        # Entropy per message
        entropies = []
        for row in byte_matrix:
            counts = np.bincount(row, minlength=256)
            probs = counts / counts.sum()
            entropy = -sum(p * np.log(p + 1e-6) for p in probs if p > 0)
            entropies.append(entropy)
        results[f'{label}_byte_entropy_mean'] = np.mean(entropies)
        results[f'{label}_byte_entropy_std'] = np.std(entropies)

        # Changed byte frequency
        changed = (byte_matrix != np.roll(byte_matrix, 1, axis=1)).sum(axis=1).mean()
        results[f'{label}_changed_bytes_mean'] = changed

    return results

def generate_visualizations(normal_df: pd.DataFrame, anomaly_df: pd.DataFrame):
    """Generate PCA, t-SNE, histograms, NN maps."""
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    combined = pd.concat([normal_df, anomaly_df])
    features = [f for f in FEATURE_COLS if f in combined.columns]
    if not features:
        return

    X = combined[features].fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    labels = combined['label']

    # PCA
    pca = PCA(n_components=2)
    X_pca = pca.fit_transform(X_scaled)
    plt.figure(figsize=(8, 6))
    plt.scatter(X_pca[labels == 0, 0], X_pca[labels == 0, 1], label='Normal', alpha=0.5)
    plt.scatter(X_pca[labels == 1, 0], X_pca[labels == 1, 1], label='Anomaly', alpha=0.5)
    plt.legend()
    plt.title('PCA Projection')
    plt.savefig(PLOTS_DIR / 'pca_projection.png')
    plt.close()

    # t-SNE if available
    if TSNE_AVAILABLE:
        tsne = TSNE(n_components=2, random_state=42)
        X_tsne = tsne.fit_transform(X_scaled)
        plt.figure(figsize=(8, 6))
        plt.scatter(X_tsne[labels == 0, 0], X_tsne[labels == 0, 1], label='Normal', alpha=0.5)
        plt.scatter(X_tsne[labels == 1, 0], X_tsne[labels == 1, 1], label='Anomaly', alpha=0.5)
        plt.legend()
        plt.title('t-SNE Projection')
        plt.savefig(PLOTS_DIR / 'tsne_projection.png')
        plt.close()

    # Feature histograms
    for feature in features[:5]:  # Top 5
        plt.figure(figsize=(8, 6))
        plt.hist(normal_df[feature].dropna(), alpha=0.5, label='Normal', bins=30)
        plt.hist(anomaly_df[feature].dropna(), alpha=0.5, label='Anomaly', bins=30)
        plt.legend()
        plt.title(f'{feature} Distribution')
        plt.savefig(PLOTS_DIR / f'{feature}_histogram.png')
        plt.close()

def generate_report(stats: Dict, nn_purity: Dict, supervised: Dict, temporal: Dict, byte_analysis: Dict) -> str:
    """Generate human-readable report."""
    report = "CAN Bus Anomaly Dataset Audit Report\n" + "="*50 + "\n\n"

    # Statistical Summary
    report += "STATISTICAL SEPARABILITY\n" + "-"*25 + "\n"
    for feature, data in stats.get('ranking', [])[:10]:
        report += f"{feature}: Cohen's d={data['cohens_d']:.3f}, KS={data['ks_stat']:.3f}, Overlap={data['overlap']:.3f}\n"

    # NN Purity
    report += "\nNEAREST-NEIGHBOR PURITY\n" + "-"*25 + "\n"
    report += f"Anomaly purity: {nn_purity.get('anomaly_purity', 0):.3f}\n"
    report += f"Normal purity: {nn_purity.get('normal_purity', 0):.3f}\n"

    # Supervised Test
    report += "\nSUPERVISED CLASSIFICATION\n" + "-"*25 + "\n"
    for model, metrics in supervised.items():
        report += f"{model.upper()}: Acc={metrics['accuracy']:.3f}, F1={metrics['f1']:.3f}, AUC={metrics['roc_auc']:.3f}\n"

    # Temporal Analysis
    report += "\nTEMPORAL ANALYSIS\n" + "-"*25 + "\n"
    for key, value in temporal.items():
        report += f"{key}: {value:.3f}\n"

    # Byte Analysis
    if byte_analysis:
        report += "\nRAW BYTE ANALYSIS\n" + "-"*25 + "\n"
        for key, value in byte_analysis.items():
            report += f"{key}: {value:.3f}\n"

    # Health Score
    separability = np.mean([d['cohens_d'] for _, d in stats.get('ranking', [])[:5]])
    nn_score = nn_purity.get('anomaly_purity', 0)
    supervised_score = np.mean([m['f1'] for m in supervised.values()])

    if separability > 1.0 and nn_score > 0.7 and supervised_score > 0.8:
        health = "GOOD"
    elif separability > 0.5 and nn_score > 0.5 and supervised_score > 0.6:
        health = "QUESTIONABLE"
    else:
        health = "WEAK"

    report += f"\nFINAL DATASET HEALTH SCORE: {health}\n"

    return report

def main():
    logger.info("Starting dataset audit...")

    # Load dataset - placeholder
    df = load_processed_dataset()

    # Sample
    normal_df, anomaly_df = sample_data(df)
    save_samples(normal_df, anomaly_df)

    # Audits
    stats = statistical_audit(normal_df, anomaly_df)
    nn_purity = nearest_neighbor_purity(normal_df, anomaly_df)
    supervised = supervised_sanity_test(normal_df, anomaly_df)
    temporal = temporal_analysis(normal_df, anomaly_df)
    byte_analysis = raw_byte_analysis(normal_df, anomaly_df)

    # Visualizations
    generate_visualizations(normal_df, anomaly_df)

    # Report
    report = generate_report(stats, nn_purity, supervised, temporal, byte_analysis)
    with open(AUDIT_DIR / "audit_report.txt", 'w') as f:
        f.write(report)

    logger.info("Audit complete. Report saved to %s", AUDIT_DIR / "audit_report.txt")
    print(report.split('\n')[-2])  # Print health score

if __name__ == "__main__":
    main()