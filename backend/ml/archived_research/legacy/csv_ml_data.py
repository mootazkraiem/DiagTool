from pathlib import Path
import logging
import re
import pandas as pd
import numpy as np

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("data_cleaning")

# 🔥 HARD-CODED PATHS (stable)
INPUT_PATH = Path(r"C:\Users\benkr\OneDrive\can_project\assets\train csv")
OUTPUT_PATH = Path(r"C:\Users\benkr\OneDrive\can_project\assets\clean traincsv")

BYTE_COLS = [f"b{i}" for i in range(8)]


# ---------------- PARSE BYTES ----------------
def parse_data_bytes(value):
    if pd.isna(value):
        return [0] * 8
    s = str(value)
    nums = [int(x) for x in re.findall(r"\d+", s)]
    nums = nums[:8] + [0] * (8 - len(nums))
    return nums


# ---------------- CLEAN DATA ----------------
def clean_dataframe(df):
    df = df.copy()

    # clean column names
    df.columns = [str(c).strip() for c in df.columns]

    # timestamp fix
    if "timestamps" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamps"], errors="coerce")
    else:
        df["timestamp"] = np.arange(len(df))

    # 🔥 FIXED LINE (pandas compatible)
    df["timestamp"] = df["timestamp"].ffill().fillna(0)

    # parse CAN bytes
    col = "CAN_DataFrame.CAN_DataFrame.DataBytes"
    if col in df.columns:
        parsed = df[col].apply(parse_data_bytes)
        bytes_df = pd.DataFrame(parsed.tolist(), columns=BYTE_COLS)
        df = pd.concat([df, bytes_df], axis=1)

    # ensure byte columns
    for c in BYTE_COLS:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).clip(0, 255)

    # clean rows
    df = df.dropna(subset=["timestamp"])
    df = df.drop_duplicates()
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


# ---------------- MAIN ----------------
def main():
    print("INPUT PATH:", INPUT_PATH)
    print("OUTPUT PATH:", OUTPUT_PATH)
    print("INPUT EXISTS:", INPUT_PATH.exists())

    if not INPUT_PATH.exists():
        print("❌ Input folder does not exist")
        return

    files = list(INPUT_PATH.rglob("*.csv"))

    if not files:
        print("❌ No CSV files found")
        return

    print(f"Found {len(files)} CSV files")

    success = 0
    failed = 0

    for file in files:
        try:
            df = pd.read_csv(file, low_memory=False)
            df_clean = clean_dataframe(df)

            # 🔥 PRESERVE FOLDER STRUCTURE
            relative_path = file.relative_to(INPUT_PATH)
            output_file = OUTPUT_PATH / relative_path

            # create folders automatically
            output_file.parent.mkdir(parents=True, exist_ok=True)

            df_clean.to_csv(output_file, index=False)

            print(f"✅ Cleaned: {relative_path}")
            success += 1

        except Exception as e:
            print(f"❌ Failed: {file} | {e}")
            failed += 1

    print("\n--- SUMMARY ---")
    print(f"Success: {success}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()