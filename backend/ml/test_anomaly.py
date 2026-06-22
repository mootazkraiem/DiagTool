import pandas as pd
import numpy as np
import os
import sys
import time

# Add root to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "data_processing"))
from log_cleaner import load_all_logs
from feature_engineering import build_features
from anomaly_model import detect_anomalies

def run_full_ml_pipeline():
    print("--- CANvision AI Anomaly Detection Pipeline ---")
    
    # 1. Load Data
    log_dirs = ["../../assets/EV-CANlogs-main", "../../assets/log_files"]
    print("\n[1/3] Loading and Cleaning Raw Logs...")
    df_raw = load_all_logs(log_dirs)
    
    if df_raw.empty:
        print("No data found.")
        return

    # 2. Feature Engineering
    print(f"\n[2/3] Building Features for {len(df_raw)} rows...")
    df_features = build_features(df_raw)

    # 3. Anomaly Detection
    print("\n[3/3] Training/Running Anomaly Detection...")
    df_results = detect_anomalies(df_features, train_mode=True)

    # --- FINAL STATS ---
    print("\n" + "="*40)
    print("🚀 PIPELINE RESULTS")
    print("="*40)
    print(f"Total rows processed: {len(df_results)}")
    
    anomalies = df_results[df_results['anomaly_label'] == -1]
    print(f"Anomalies detected:   {len(anomalies)} ({len(anomalies)/len(df_results)*100:.2f}%)")
    
    if not anomalies.empty:
        print("\nTop 5 High-Severity Anomalies:")
        top_anomalies = anomalies.sort_values(by='severity', ascending=False).head(5)
        print(top_anomalies[['timestamp', 'can_id', 'severity', 'anomaly_score']])

    print("="*40)
    print(f"Models saved in: models/")

if __name__ == "__main__":
    import os
    # Ensure working directory is correct
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    run_full_ml_pipeline()
