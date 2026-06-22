import pandas as pd
import numpy as np
import os
import time
import logging
import sys

# Add data_processing to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "data_processing"))
from log_cleaner import load_all_logs
from feature_engineering import build_features

# Import Models
from anomaly_model import detect_anomalies as run_iforest
from lof_model import detect_lof as run_lof
from ocsvm_model import detect_ocsvm as run_ocsvm

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')
logger = logging.getLogger('model_runner')

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

def ensure_results_dir():
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
        logger.info(f"Created results directory: {RESULTS_DIR}")

def run_multi_model_pipeline():
    ensure_results_dir()
    
    # 1. Load Data
    log_dirs = ["../../assets/EV-CANlogs-main", "../../assets/log_files"]
    logger.info("Loading assets...")
    df_raw = load_all_logs(log_dirs)
    
    if df_raw.empty:
        logger.error("No data found.")
        return

    # To ensure LOF and OCSVM finish in reasonable time for testing, 
    # we limit to a representative sample if rows > 100k
    if len(df_raw) > 100000:
        logger.warning(f"Large dataset detected ({len(df_raw)} rows). Sampling 100,000 rows for multi-model comparison.")
        df_raw = df_raw.sample(n=100000, random_state=42).sort_values(by='timestamp')

    # 2. Feature Engineering
    logger.info("Building features...")
    df_features = build_features(df_raw)

    models = [
        ("Isolation Forest", run_iforest, "isolation_results.csv"),
        ("LOF", run_lof, "lof_results.csv"),
        ("One-Class SVM", run_ocsvm, "ocsvm_results.csv")
    ]

    summary_data = []
    all_results = {}

    for name, run_fn, filename in models:
        logger.info(f"--- Running {name} ---")
        start = time.time()
        res = run_fn(df_features.copy())
        elapsed = time.time() - start
        
        # Save results
        res_path = os.path.join(RESULTS_DIR, filename)
        res.to_csv(res_path, index=False)
        
        # Collect stats
        anomaly_pct = (len(res[res['anomaly_label'] == -1]) / len(res)) * 100
        mean_severity = res['severity'].mean()
        
        summary_data.append({
            "Model": name,
            "Anomaly %": f"{anomaly_pct:.2f}%",
            "Mean Severity": f"{mean_severity:.2f}",
            "Runtime": f"{elapsed:.2f}s"
        })
        
        # Store for consistency check (top 1% indices)
        top_indices = set(res.sort_values(by='severity', ascending=False).head(int(len(res)*0.01)).index)
        all_results[name] = top_indices

    # 3. Print Evaluation Summary
    print("\n" + "="*60)
    print("MODEL EVALUATION SUMMARY")
    print("="*60)
    summary_df = pd.DataFrame(summary_data)
    print(summary_df.to_string(index=False))
    print("="*60)

    # 4. Consistency Check (Overlap between top 1% anomalies)
    print("\nCONSISTENCY CHECK (Top 1% Overlap)")
    names = [m[0] for m in models]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            n1, n2 = names[i], names[j]
            overlap = len(all_results[n1].intersection(all_results[n2]))
            total_top = len(all_results[n1])
            print(f"Overlap {n1} vs {n2}: {overlap} rows ({overlap/total_top*100:.1f}% match)")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    run_multi_model_pipeline()
