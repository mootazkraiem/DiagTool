import json
import os

def load_and_clean_transmit(json_path):
    """
    Loads and cleans a UDS transmit list from JSON.
    """
    if not os.path.exists(json_path):
        print(f"Error: JSON file {json_path} not found.")
        return []

    try:
        with open(json_path, 'r') as f:
            raw_data = json.load(f)
    except Exception as e:
        print(f"Error loading UDS JSON: {e}")
        return []

    # Handle nested structure (e.g., {"can_1": {"transmit": [...]}})
    if isinstance(raw_data, dict):
        if 'transmit' in raw_data:
            data = raw_data['transmit']
        elif 'can_1' in raw_data and 'transmit' in raw_data['can_1']:
            data = raw_data['can_1']['transmit']
        else:
            # Fallback to search for any 'transmit' key
            data = None
            for key in raw_data:
                if isinstance(raw_data[key], dict) and 'transmit' in raw_data[key]:
                    data = raw_data[key]['transmit']
                    break
            if data is None:
                print("Error: Could not find 'transmit' list in JSON.")
                return []
    else:
        data = raw_data

    if not isinstance(data, list):
        print("Error: UDS transmit list must be a JSON array.")
        return []

    cleaned_requests = []
    seen_names = set()

    for item in data:
        # 1. Extract only active requests (state == 1)
        if item.get('state') != 1:
            continue

        # 2. Validate essential fields
        name = item.get('name')
        raw_id = item.get('id')
        raw_payload = item.get('data')
        interval = item.get('interval', 0)

        if not name or raw_id is None or raw_payload is None:
            continue

        # 3. Remove duplicates by name
        if name in seen_names:
            continue

        # 4. Convert formats
        try:
            # Convert ID (handle both int and hex string)
            if isinstance(raw_id, str):
                can_id = int(raw_id, 16)
            else:
                can_id = int(raw_id)

            # Convert Data to bytes (handle list of ints or space-separated hex)
            if isinstance(raw_payload, list):
                payload = bytes(raw_payload)
            elif isinstance(raw_payload, str):
                # Remove spaces and convert hex to bytes
                clean_hex = raw_payload.replace(" ", "")
                payload = bytes.fromhex(clean_hex)
            else:
                continue

        except (ValueError, TypeError) as e:
            print(f"Validation failed for request '{name}': {e}")
            continue

        cleaned_requests.append({
            "name": name,
            "can_id": can_id,
            "payload": payload,
            "interval": interval
        })
        seen_names.add(name)

    return cleaned_requests

def load_all_transmits(directory_paths):
    """
    Recursively finds and merges all UDS transmit JSONs.
    """
    if isinstance(directory_paths, str):
        directory_paths = [directory_paths]
        
    all_requests = []
    seen_names = set()
    
    for root_dir in directory_paths:
        if not os.path.exists(root_dir):
            continue
            
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.lower().endswith('.json'):
                    full_path = os.path.join(root, file)
                    print(f"  -> Loading UDS List: {file}")
                    reqs = load_and_clean_transmit(full_path)
                    
                    for r in reqs:
                        if r['name'] not in seen_names:
                            all_requests.append(r)
                            seen_names.add(r['name'])
    
    return all_requests
