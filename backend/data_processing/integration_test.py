import os
from log_cleaner import load_and_clean_logs, load_all_logs
from dbc_cleaner import load_and_clean_dbc, load_all_dbcs
from uds_cleaner import load_and_clean_transmit, load_all_transmits

def run_integration_test():
    print("--- CANvision Data Cleaning Pipeline Test ---")
    
    # Paths using actual assets
    asset_root = os.path.join("..", "..", "assets")
    log_dirs = [
        os.path.join(asset_root, "EV-CANlogs-main"),
        os.path.join(asset_root, "log_files")
    ]
    tesla_dbc = os.path.join(asset_root, "dbc_files", "can1-tesla-model-3.dbc")
    uds_dirs = [os.path.join(asset_root, "transmit_lists")]
    
    # 1. Load and clean all logs
    print(f"\n[1/3] Aggregating Logs from: {', '.join(log_dirs)}")
    df_logs = load_all_logs(log_dirs)
    
    # 2. Load and clean all DBCs
    print(f"\n[2/3] Loading explicit DBC: {tesla_dbc}")
    cleaned_messages = load_all_dbcs([tesla_dbc])
    
    # 3. Load and clean all UDS transmit lists
    print(f"\n[3/3] Aggregating UDS from: {', '.join(uds_dirs)}")
    cleaned_uds = load_all_transmits(uds_dirs)
    
    # --- RESULTS ---
    print("\n" + "="*40)
    print("PIPELINE STATISTICS")
    print("="*40)
    print(f"Cleaned Log Rows:      {len(df_logs)}")
    print(f"Cleaned DBC Messages:  {len(cleaned_messages)}")
    print(f"Cleaned UDS Requests:  {len(cleaned_uds)}")
    print("="*40)
    
    if not df_logs.empty:
        print("\nSample Log Data:")
        print(df_logs.head())
        
    if cleaned_messages:
        print("\nCleaned DBC Messages:")
        for msg in cleaned_messages:
            print(f" - {msg.name} (ID: 0x{msg.frame_id:X}) | Signals: {len(msg.signals)}")

    if cleaned_uds:
        print("\nCleaned UDS Requests:")
        for req in cleaned_uds:
            print(f" - {req['name']} (ID: 0x{req['can_id']:X}) | Payload: {req['payload'].hex(' ')}")

if __name__ == "__main__":
    # Ensure we are in the right directory to find the modules
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    run_integration_test()
