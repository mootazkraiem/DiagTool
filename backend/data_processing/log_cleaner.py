import pandas as pd
import numpy as np
import re
import os
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')
logger = logging.getLogger('log_cleaner')

def parse_hex_or_int(val):
    """
    Helper to parse hex or decimal values safely.
    Used for CAN IDs and Bytes.
    """
    if pd.isna(val):
        return 0
    s = str(val).strip().lower()
    if not s:
        return 0
    try:
        if s.startswith('0x') or any(c in 'abcdef' for c in s):
            return int(s, 16)
        return int(float(s))
    except (ValueError, TypeError):
        return 0

def load_and_clean_logs(file_path):
    """
    Optimized entry point to load and clean a single CAN log file.
    Uses vectorized operations for speed.
    """
    start_time = time.time()
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return pd.DataFrame()

    ext = os.path.splitext(file_path)[1].lower()
    df = pd.DataFrame()

    try:
        if ext == '.csv':
            # 1. Handle CSV format with optimized parameters
            df = pd.read_csv(file_path, encoding="utf-8", on_bad_lines="skip", low_memory=False)
            df.columns = [str(c).strip().lower() for c in df.columns]
            
            # Map common column names
            rename_map = {
                'time stamp': 'timestamp', 'ts': 'timestamp', 'time': 'timestamp',
                'id': 'can_id', 'cid': 'can_id', 'can id': 'can_id', 'canid': 'can_id',
                'd1': 'b0', 'd2': 'b1', 'd3': 'b2', 'd4': 'b3',
                'd5': 'b4', 'd6': 'b5', 'd7': 'b6', 'd8': 'b7',
                'data0': 'b0', 'data1': 'b1', 'data2': 'b2', 'data3': 'b3',
                'data4': 'b4', 'data5': 'b5', 'data6': 'b6', 'data7': 'b7'
            }
            df = df.rename(columns=rename_map)
            
            required = ['timestamp', 'can_id', 'b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7']
            # If some byte columns are missing, fill them with 0
            for col in required:
                if col not in df.columns:
                    df[col] = 0
            
            df = df[required]

            # Vectorized Conversion - CAN ID and Bytes often need hex parsing
            # We convert to string first to ensure apply(parse_hex_or_int) works consistently
            df['can_id'] = df['can_id'].astype(str).apply(parse_hex_or_int)
            for i in range(8):
                df[f'b{i}'] = df[f'b{i}'].astype(str).apply(parse_hex_or_int)
            df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')

        else:
            # 2. Handle line-by-line format (.log or .txt)
            # Optimized line processing using list comprehension
            with open(file_path, 'r', encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            
            pattern = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")
            
            def parse_line(line):
                m = pattern.search(line)
                if not m: return None
                ts = float(m[1])
                cid = int(m[2], 16)
                data = m[3]
                b = [int(data[i:i+2], 16) for i in range(0, min(len(data), 16), 2)]
                return [ts, cid] + b + [0]*(8-len(b))

            extracted = [parse_line(l) for l in lines]
            extracted = [e for e in extracted if e is not None]
            
            if extracted:
                df = pd.DataFrame(extracted, columns=['timestamp', 'can_id', 'b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7'])
            else:
                return pd.DataFrame()

        if df.empty:
            return pd.DataFrame()

        # 3. Vectorized Validation
        initial_rows = len(df)
        
        # Boolean Mask Validation
        mask = (df['timestamp'].notna()) & (df['timestamp'] >= 0) & \
               (df['can_id'].notna()) & (df['can_id'] > 0)
        
        for i in range(8):
            col = f'b{i}'
            mask &= (df[col].notna()) & (df[col] >= 0) & (df[col] <= 255)
            
        df = df[mask].copy()
        
        if df.empty:
            elapsed = time.time() - start_time
            logger.debug(f"File {os.path.basename(file_path)}: All {initial_rows} rows dropped in {elapsed:.2f}s")
            return pd.DataFrame()

        # Casting
        df['can_id'] = df['can_id'].astype(np.int64)
        for i in range(8):
            df[f'b{i}'] = df[f'b{i}'].astype(np.int16)

        # Cleanup
        df = df.drop_duplicates()
        df = df.sort_values(by='timestamp')
        
        # Normalize
        if not df.empty:
            df['timestamp'] = df['timestamp'] - df['timestamp'].min()

        elapsed = time.time() - start_time
        logger.info(f"Processed {os.path.basename(file_path)}: {len(df)} rows in {elapsed:.2f}s (dropped {initial_rows - len(df)})")
        
        return df

    except Exception as e:
        logger.error(f"Critical error processing {file_path}: {e}")
        return pd.DataFrame()

def load_all_logs(directory_paths):
    """
    Crawls directories and aggregates all valid CAN data using optimized aggregation.
    """
    global_start_time = time.time()
    if isinstance(directory_paths, str):
        directory_paths = [directory_paths]
    
    all_dfs = []
    total_files = 0

    supported_extensions = ('.log', '.csv', '.txt')

    for root_dir in directory_paths:
        if not os.path.exists(root_dir):
            logger.warning(f"Directory not found: {root_dir}")
            continue
            
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.lower().endswith(supported_extensions) and "readme" not in file.lower():
                    total_files += 1
                    full_path = os.path.join(root, file)
                    df = load_and_clean_logs(full_path)
                    if not df.empty:
                        all_dfs.append(df)

    if not all_dfs:
        logger.warning("No valid CAN data found.")
        return pd.DataFrame()
        
    # Optimized Aggregation
    final_df = pd.concat(all_dfs, ignore_index=True)
    final_df = final_df.drop_duplicates()
    final_df = final_df.sort_values(by='timestamp')
    
    total_elapsed = time.time() - global_start_time
    logger.info("="*40)
    logger.info("FINAL PERFORMANCE STATS")
    logger.info(f"Total Files Processed:  {total_files}")
    logger.info(f"Total Valid Rows:       {len(final_df)}")
    logger.info(f"Total Processing Time:  {total_elapsed:.2f}s")
    logger.info(f"Average Time per File:  {total_elapsed/total_files:.2f}s" if total_files > 0 else "N/A")
    logger.info("="*40)
    
    return final_df
