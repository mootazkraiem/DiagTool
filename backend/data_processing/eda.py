import os
import pandas as pd
import matplotlib.pyplot as plt
from log_cleaner import load_and_clean_logs
from dbc_cleaner import load_and_clean_dbc

def run_eda(log_path, dbc_path=None):
    """
    Performs Exploratory Data Analysis (EDA) on CAN bus data.
    """
    print("--- CANvision Exploratory Data Analysis (EDA) ---")

    # 1. Load Data
    print(f"Loading logs: {log_path}")
    df = load_and_clean_logs(log_path)
    if df.empty:
        print("Error: No data to analyze.")
        return

    # Optional DBC Loading
    db_messages = []
    if dbc_path and os.path.exists(dbc_path):
        print(f"Loading DBC: {dbc_path}")
        db_messages = load_and_clean_dbc(dbc_path)
    else:
        print("No DBC provided or file missing. Enhanced visualization skipped.")

    # 2. Data Inspection
    print("\n" + "="*40)
    print("DATA INSPECTION")
    print("="*40)
    print(f"Total Rows:           {len(df)}")
    print(f"Unique CAN IDs:       {df['can_id'].nunique()}")
    print("\nRaw Data Stats:")
    print(df.describe())

    # 3. Visualization Setup
    plt.style.use('bmh') # Clean professional style
    fig = plt.figure(figsize=(15, 12))
    
    # --- SUBPLOT 1: CAN ID Distribution (Top 10) ---
    plt.subplot(2, 2, 1)
    id_counts = df['can_id'].value_counts().head(10)
    # Convert to hex for readable labels
    hex_labels = [f"0x{int(x):X}" for x in id_counts.index]
    id_counts.index = hex_labels
    id_counts.plot(kind='bar', color='skyblue', edgecolor='black')
    plt.title("Top 10 CAN IDs by Frequency")
    plt.xlabel("CAN ID (Hex)")
    plt.ylabel("Frequency")
    plt.xticks(rotation=45)

    # --- SUBPLOT 2: Timing Analysis (Timestamp Diff) ---
    plt.subplot(2, 2, 2)
    # Global timing diff (ignoring specific IDs for high-level view)
    timing_diffs = df['timestamp'].diff().dropna()
    plt.hist(timing_diffs, bins=50, color='salmon', edgecolor='black', alpha=0.7)
    plt.title("Inter-Arrival Timing Distribution")
    plt.xlabel("Delta Time (Seconds)")
    plt.ylabel("Log Frequency")

    # --- SUBPLOT 3: Byte Heatmap/Distribution (High level) ---
    plt.subplot(2, 2, 3)
    byte_cols = [f'b{i}' for i in range(8)]
    df[byte_cols].boxplot()
    plt.title("Byte Distribution (b0-b7)")
    plt.xlabel("Byte Index")
    plt.ylabel("Byte Value (0-255)")

    # --- SUBPLOT 4: Activity Scatter ---
    plt.subplot(2, 2, 4)
    plt.scatter(df['timestamp'], df['can_id'], alpha=0.5, s=10, c='navy')
    plt.title("CAN Activity Scatter Map")
    plt.xlabel("Time (Normalized Seconds)")
    plt.ylabel("CAN ID (Decimal)")

    plt.tight_layout()
    plt.savefig("eda_raw_can.png")
    print("\n[v] Raw CAN visualizations saved to 'eda_raw_can.png'")

    # 4. DBC Enhanced Visualization (Optional)
    if db_messages:
        analyze_signals(df, db_messages)

def analyze_signals(df, db_messages):
    """
    Decodes signals using DBC and plots them over time.
    """
    print("\n" + "="*40)
    print("SIGNAL DECODING (DBC ENHANCED)")
    print("="*40)

    # Map frame IDs to message objects for fast lookup
    msg_map = {msg.frame_id: msg for msg in db_messages}
    
    decoded_results = []

    for _, row in df.iterrows():
        can_id = int(row['can_id'])
        if can_id in msg_map:
            msg_def = msg_map[can_id]
            # Construct payload
            data = bytes([int(row[f'b{i}']) for i in range(8)])
            try:
                decoded = msg_def.decode(data)
                decoded['timestamp'] = row['timestamp']
                decoded['can_id_hex'] = f"0x{can_id:X}"
                decoded_results.append(decoded)
            except Exception:
                continue
    
    if not decoded_results:
        print("No signals could be decoded from the provided logs and DBC.")
        return

    # Convert decoded signals to DataFrame
    df_signals = pd.DataFrame(decoded_results)
    
    # Identify key signals to plot (first 4 numeric signals)
    numeric_cols = df_signals.select_dtypes(include=['number']).columns
    plot_signals = [col for col in numeric_cols if col != 'timestamp']
    plot_signals = plot_signals[:4] # Limit to 4 for readability

    if not plot_signals:
        print("No numeric signals found for plotting.")
        return

    print(f"Plotting key signals: {', '.join(plot_signals)}")

    # Plot Signals
    plt.figure(figsize=(15, 10))
    for i, signal in enumerate(plot_signals):
        plt.subplot(len(plot_signals), 1, i + 1)
        plt.plot(df_signals['timestamp'], df_signals[signal], label=signal, color='forestgreen', linewidth=1.5)
        plt.title(f"Signal Analysis: {signal}")
        plt.xlabel("Time (s)")
        plt.ylabel("Value")
        plt.legend(loc='upper right')
        plt.grid(True, linestyle='--', alpha=0.7)

    plt.tight_layout()
    plt.savefig("eda_signals.png")
    print("[v] Decoded signal visualizations saved to 'eda_signals.png'")

if __name__ == "__main__":
    # Use relative paths assuming run from project root or data_processing folder
    # We'll use the sample data created in Task 4 of previous request
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sample_log = os.path.join(root, "assets", "EV-CANlogs-main", "Tesla", "Model 3", "tesla-model3-battery-only.log.log")
    sample_dbc = os.path.join(root, "assets", "dbc_files", "can1-tesla-model-3.dbc")
    
    run_eda(sample_log, sample_dbc)
