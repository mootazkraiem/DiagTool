import pandas as pd
import numpy as np
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
import joblib
import os
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')
logger = logging.getLogger('lof_model')

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models")
MODEL_PATH = os.path.join(MODEL_DIR, "lof_model.joblib")
SCALER_PATH = os.path.join(MODEL_DIR, "lof_scaler.joblib")

FEATURE_COLS = [
    'time_diff', 'freq', 'byte_mean', 'byte_std', 
    'byte_min', 'byte_max', 'rolling_mean', 'rolling_std', 'entropy'
]

def save_model(model, scaler):
    if not os.path.exists(MODEL_DIR): os.makedirs(MODEL_DIR)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)

def detect_lof(df: pd.DataFrame, train_mode: bool = True) -> pd.DataFrame:
    """
    Local Outlier Factor (LOF) anomaly detection.
    """
    if df.empty: return df
    start_time = time.time()
    
    X = df[FEATURE_COLS].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # LOF with novelty=True allows prediction on new data
    # n_neighbors=20 is standard for most CAN timing anomalies
    model = LocalOutlierFactor(n_neighbors=20, contamination=0.01, novelty=True, n_jobs=-1)
    
    logger.info(f"Training LOF on {len(df)} rows...")
    model.fit(X_scaled)
    save_model(model, scaler)

    # Output generation
    results = df[['timestamp', 'can_id']].copy()
    results['anomaly_label'] = model.predict(X_scaled)
    results['anomaly_score'] = model.decision_function(X_scaled)
    
    # Severity (0-100)
    scores = results['anomaly_score'].values
    min_s, max_s = np.min(scores), np.max(scores)
    if max_s - min_s > 0:
        results['severity'] = ((max_s - scores) / (max_s - min_s)) * 100
    else:
        results['severity'] = 0.0

    logger.info(f"LOF complete in {time.time() - start_time:.2f}s")
    return results
