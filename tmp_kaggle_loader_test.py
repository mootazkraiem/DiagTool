from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from backend.ml.feature_engineering import load_kaggle_dataset
p = Path('C:/Users/benkr/OneDrive/can_project/assets/archive/normal_run_data.txt')
df = load_kaggle_dataset(p)
print(df.shape)
print(df.head().to_dict())
