import cantools
import os

def load_and_clean_dbc(dbc_path, valid_can_ids=None):
    """
    Loads a DBC file and filters out invalid or empty messages.
    """
    if not os.path.exists(dbc_path):
        print(f"Error: DBC file {dbc_path} not found.")
        return []

    try:
        db = cantools.database.load_file(dbc_path)
    except Exception as e:
        print(f"Error loading DBC: {e}")
        return []

    cleaned_messages = []
    seen_ids = set()

    for message in db.messages:
        # 1. Skip messages with no signals
        if not message.signals:
            continue

        # 2. Skip duplicates (DBCs shouldn't have them, but for robustness)
        if message.frame_id in seen_ids:
            continue

        # 3. If valid_can_ids is provided, filter by them
        if valid_can_ids is not None:
            if message.frame_id not in valid_can_ids:
                continue

        cleaned_messages.append(message)
        seen_ids.add(message.frame_id)

    return cleaned_messages

def load_all_dbcs(dbc_paths):
    """
    Loads an explicit list of DBC files and merges cleaned messages.
    Recursive directory loading is intentionally disabled to avoid
    cross-manufacturer/archive DBC contamination.
    """
    if isinstance(dbc_paths, str):
        dbc_paths = [dbc_paths]

    all_messages = []
    seen_ids = set()

    for dbc_path in dbc_paths:
        if not os.path.exists(dbc_path):
            continue
        if not dbc_path.lower().endswith(".dbc"):
            continue
        print(f"  -> Loading DBC: {os.path.basename(dbc_path)}")
        msgs = load_and_clean_dbc(dbc_path)
        for m in msgs:
            if m.frame_id not in seen_ids:
                all_messages.append(m)
                seen_ids.add(m.frame_id)

    return all_messages
