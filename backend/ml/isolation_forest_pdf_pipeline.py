from pathlib import Path
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("iforest_pipeline")

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[2]

DATA_ROOT = PROJECT_ROOT / "assets" / "train csv"

FEATURE_COLS = [
    "time_diff",
    "freq",
    "byte_mean",
    "byte_std",
    "byte_min",
    "byte_max",
    "rolling_mean",
    "rolling_std",
    "entropy",
]

# ---------------- LOAD DATA ----------------
def load_data():
    print("DATA ROOT:", DATA_ROOT)
    print("EXISTS:", DATA_ROOT.exists())

    files = list(DATA_ROOT.rglob("*.csv"))
    print("CSV FILES FOUND:", len(files))

    if not files:
        raise RuntimeError(f"No CSV files found in {DATA_ROOT}")

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, low_memory=False)
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Skipped {f}: {e}")

    df = pd.concat(dfs, ignore_index=True)
    logger.info(f"Loaded rows: {len(df):,}")

    print("COLUMNS:", df.columns)
    print(df.head())

    return df


# ---------------- EXTRACT BYTES ----------------
def extract_bytes(df):
    df = df.copy()

    col = "CAN_DataFrame.CAN_DataFrame.DataBytes"

    if col not in df.columns:
        print("❌ DataBytes column not found")
        for i in range(8):
            df[f"b{i}"] = 0
        return df

    def parse_bytes(x):
        try:
            x = str(x).replace("[", "").replace("]", "").strip()
            nums = [int(i) for i in x.split()]
            nums += [0] * (8 - len(nums))
            return nums[:8]
        except:
            return [0] * 8

    byte_values = df[col].apply(parse_bytes)

    for i in range(8):
        df[f"b{i}"] = byte_values.apply(lambda x: x[i])

    return df


# ---------------- FEATURE ENGINEERING ----------------
def build_features(df):
    df = df.copy()

    # FIX timestamp column
    if "timestamps" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamps"], errors="coerce").fillna(0)
    else:
        df["timestamp"] = np.arange(len(df))

    df = df.sort_values("timestamp").reset_index(drop=True)

    df["time_diff"] = df["timestamp"].diff().fillna(0)

    safe_diff = df["time_diff"].replace(0, np.nan)
    df["freq"] = (1 / safe_diff).replace([np.inf, -np.inf], 0).fillna(0)

    byte_cols = [f"b{i}" for i in range(8)]

    df["byte_mean"] = df[byte_cols].mean(axis=1)
    df["byte_std"] = df[byte_cols].std(axis=1).fillna(0)
    df["byte_min"] = df[byte_cols].min(axis=1)
    df["byte_max"] = df[byte_cols].max(axis=1)

    df["rolling_mean"] = df["byte_mean"].rolling(10, min_periods=1).mean()
    df["rolling_std"] = df["byte_mean"].rolling(10, min_periods=1).std().fillna(0)

    df["entropy"] = -df["byte_mean"] * np.log(df["byte_mean"] + 1e-6)

    df = df.replace([np.inf, -np.inf], 0).fillna(0)

    return df


# ---------------- TRAIN ----------------
def train_model(df):
    X = df[FEATURE_COLS].values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=100,
        contamination=0.01,
        random_state=42,
        n_jobs=-1,
    )

    model.fit(X_scaled)

    return model, scaler


# ---------------- EVALUATE ----------------
def evaluate(df, model, scaler):
    X = df[FEATURE_COLS].values
    X_scaled = scaler.transform(X)

    labels = model.predict(X_scaled)
    scores = model.decision_function(X_scaled)

    df["label"] = labels
    df["score"] = scores

    anomaly_ratio = (labels == -1).mean() * 100
    logger.info(f"Anomaly ratio: {anomaly_ratio:.2f}%")

    return df


# ---------------- PLOT ----------------
def plot(df):
    # Histogram
    plt.figure()
    plt.hist(df["score"], bins=50)
    plt.title("Anomaly Score Histogram")
    plt.show()

    # PCA
    X = df[FEATURE_COLS].values
    X_scaled = StandardScaler().fit_transform(X)

    pca = PCA(n_components=2)
    X_pca = pca.fit_transform(X_scaled)

    normal = df["label"] == 1
    anomaly = df["label"] == -1

    plt.figure()
    plt.scatter(X_pca[normal, 0], X_pca[normal, 1], s=5)
    plt.scatter(X_pca[anomaly, 0], X_pca[anomaly, 1], s=10)
    plt.title("PCA Projection")
    plt.show()


# ---------------- MAIN ----------------
def main():
    df = load_data()

    df = extract_bytes(df)   # 🔥 CORRECTED

    df = build_features(df)

    model, scaler = train_model(df)
    df = evaluate(df, model, scaler)

    plot(df)

    print(df.describe())

    logger.info("✅ Model trained successfully")


if __name__ == "__main__":
    main()