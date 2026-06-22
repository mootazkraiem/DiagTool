import pandas as pd
import numpy as np
import joblib
import os
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')
logger = logging.getLogger('anomaly_model')

# Model Paths
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models")
MODEL_PATH = os.path.join(MODEL_DIR, "isolation_forest.joblib")
SCALER_PATH = os.path.join(MODEL_DIR, "scaler.joblib")

# Feature set for ML (Must match training)
FEATURE_COLS = [
    'time_diff', 'freq', 'byte_mean', 'byte_std', 
    'byte_min', 'byte_max', 'rolling_mean', 'rolling_std', 'entropy'
]

# Global cache for model and scaler to avoid repeated disk I/O
_MODEL_CACHE = None
_SCALER_CACHE = None

def load_artifacts():
    """Loads model and scaler from disk with caching."""
    global _MODEL_CACHE, _SCALER_CACHE
    if _MODEL_CACHE is not None and _SCALER_CACHE is not None:
        return _MODEL_CACHE, _SCALER_CACHE

    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        _MODEL_CACHE = joblib.load(MODEL_PATH)
        _SCALER_CACHE = joblib.load(SCALER_PATH)
        logger.info("Inference artifacts loaded successfully.")
        return _MODEL_CACHE, _SCALER_CACHE
    
    logger.error("Model artifacts missing! Please run train_model.py first.")
    return None, None

def predict(df: pd.DataFrame) -> pd.DataFrame:
    """
    ML Inference Module: Uses saved artifacts to detect anomalies.
    Returns DataFrame with anomaly_label, anomaly_score, and severity.
    """
    if df.empty:
        return df

    start_time = time.time()
    model, scaler = load_artifacts()
    
    if model is None or scaler is None:
        return df

    # 1. Feature Selection
    available_features = [c for c in FEATURE_COLS if c in df.columns]
    X = df[available_features].values

    # 2. Scaling (Transform only, no fit!)
    X_scaled = scaler.transform(X)

    # 3. Prediction
    df['anomaly_label'] = model.predict(X_scaled)
    df['anomaly_score'] = model.decision_function(X_scaled)

    # 4. Severity Calculation (0 - 100)
    scores = df['anomaly_score'].values
    min_score, max_score = np.min(scores), np.max(scores)
    
    if max_score - min_score > 0:
        df['severity'] = ((max_score - scores) / (max_score - min_score)) * 100
    else:
        df['severity'] = 0.0

    elapsed = time.time() - start_time
    logger.info(f"Inference complete: {len(df)} rows in {elapsed:.2f}s")
    
    return df

# For backward compatibility with existing tests
def detect_anomalies(df: pd.DataFrame, train_mode: bool = False) -> pd.DataFrame:
    """Wrapper for backward compatibility."""
    return predict(df)
