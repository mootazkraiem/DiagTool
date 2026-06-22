import sys
from pathlib import Path

results = []
results.append(f"Python: {sys.version}")

# Core dependency checks
for mod in ["numpy", "pandas", "sklearn", "fastapi", "uvicorn", "joblib"]:
    try:
        __import__(mod)
        results.append(f"{mod}: OK")
    except ImportError:
        results.append(f"{mod}: FAILED")

# New project structure checks
imports_to_test = [
    "backend.api.server",
    "backend.api.mock_signals",
    "backend.ml.anomaly",
    "backend.ml.ai_model",
    "backend.ml.engine",
    "backend.ml.session_data",
    "backend.data_processing.can_reader",
    "backend.data_processing.decoder",
    "backend.data_processing.parser",
    "backend.data_processing.feature_engineering",
]

for imp in imports_to_test:
    try:
        __import__(imp, fromlist=["*"])
        results.append(f"Import {imp}: OK")
    except Exception as e:
        results.append(f"Import {imp}: FAILED - {e}")

# Path checks
paths_to_test = [
    "data/raw/logs/tesla_log.log",
    "data/uds/default_vehicle.json",
    "data/uds/mock_signals.json",
    "models/isolation_forest.joblib",
]

for p in paths_to_test:
    if Path(p).exists():
        results.append(f"Path {p}: OK")
    else:
        results.append(f"Path {p}: MISSING")

print("\n".join(results))
with open("test_result.txt", "w") as f:
    f.write("\n".join(results))
