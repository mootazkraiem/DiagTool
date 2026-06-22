import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[0] / "assets"
folders = [
    "models",
    "processed_features",
    "clean traincsv",
    "clean_traincsv",
    "train_csv",
    "validation_csv",
]

for folder in folders:
    path = root / folder
    if path.exists():
        print(f"Removing {path}")
        shutil.rmtree(path)
    else:
        print(f"Not found {path}")
