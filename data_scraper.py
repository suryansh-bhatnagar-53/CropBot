import requests
import json
import time
import os
import csv

def fetch_nutrient_data():
    api_url = "https://soilhealth4.dac.gov.in/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # The ultimate data query
    data_query = """
    query GetNutrientDashboardForPortal($state: ID, $district: ID, $block: ID, $village: ID, $cycle: String, $count: Boolean, $scheme: String) {
      getNutrientDashboardForPortal(
        state: $state
        district: $district
        block: $block
        village: $village
        cycle: $cycle
        count: $count
        scheme: $scheme
      )
    }
    """
    
    # Variables you noted from your Network tab
    target_cycle = "2026-27"
    target_scheme = "660f941a5c8405ca8375c7c6"

    # 1. Load the Master Map
    if not os.path.exists("india_villages_map.json"):
        print("Error: Master map not found!")
        return
        
    with open("india_villages_map.json", "r") as f:
        master_map = json.load(f)

    # 2. Build our "Memory" of already processed villages
    csv_filename = "india_soil_health_data.csv"
    processed_villages = set()
    
    if os.path.exists(csv_filename):
        with open(csv_filename, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None) # Skip the header
            for row in reader:
                if len(row) >= 14: # Assuming Village ID is stored in the row
                    processed_villages.add(row[13]) # Add the Village ID to our memory set

    print(f"Found {len(processed_villages)} villages already processed. Resuming...\n")

    # 3. Setup the CSV file for appending
    csv_file = open(csv_filename, "a", newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    
    # Write header if file is totally empty
    if os.stat(csv_filename).st_size == 0:
        writer.writerow([
            "State", "District", "Block", "Village", 
            "N_High", "N_Medium", "N_Low", 
            "P_High", "P_Medium", "P_Low", 
            "K_High", "K_Medium", "K_Low", 
            "Village_ID" # We save the ID so the script can remember it later!
        ])

    # 4. The Grand Loop
    for state_name, state_data in master_map.items():
        state_id = state_data.get("state_id")
        
        for dist_name, dist_data in state_data.get("districts", {}).items():
            # Skip if Level 3 didn't finish
            if isinstance(dist_data, str): continue 
            dist_id = dist_data.get("id")
            
            for block_name, block_data in dist_data.get("blocks", {}).items():
                # Skip if Level 4 didn't finish
                if isinstance(block_data, str): continue
                block_id = block_data.get("id")
                
                for vil_name, vil_id in block_data.get("villages", {}).items():
                    
                    # --- RESUME LOGIC ---
                    if vil_id in processed_villages:
                        continue # Instantly skip this village if we already have it!
                    # --------------------
                    
                    print(f"Fetching data for: {vil_name} ({dist_name}, {state_name})")
                    
                    payload = {
                        "operationName": "GetNutrientDashboardForPortal",
                        "query": data_query,
                        "variables": {
                            "state": state_id,
                            "district": dist_id,
                            "block": block_id,
                            "village": vil_id,
                            "cycle": target_cycle,
                            "scheme": target_scheme,
                            "count": False
                        }
                    }

                    try:
                        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
                        
                        if response.status_code == 200:
                            data = response.json().get("data", {}).get("getNutrientDashboardForPortal", [])
                            
                            # Safely extract the numbers (default to 0 if they don't exist)
                            if data and isinstance(data, list) and len(data) > 0:
                                results = data[0].get("results", {})
                                n = results.get("n", {})
                                p = results.get("p", {})
                                k = results.get("k", {})
                                
                                writer.writerow([
                                    state_name, dist_name, block_name, vil_name,
                                    n.get("High", 0), n.get("Medium", 0), n.get("Low", 0),
                                    p.get("High", 0), p.get("Medium", 0), p.get("Low", 0),
                                    k.get("High", 0), k.get("Medium", 0), k.get("Low", 0),
                                    vil_id
                                ])
                                csv_file.flush() # Force save to the hard drive immediately
                                processed_villages.add(vil_id)
                            else:
                                print(f"  -> No data found for {vil_name}.")
                        else:
                            print(f"  -> FAILED. Status Code: {response.status_code}")
                            
                    except requests.exceptions.RequestException as e:
                        print(f"  -> Connection Error: {e}")
                        # Don't crash the script on a blip in the internet, just wait and continue
                        time.sleep(5) 
                    
                    # CRITICAL: Be a good citizen to the government servers
                    time.sleep(2) 
                    
    csv_file.close()
    print("\nScraping completely finished!")

if __name__ == "__main__":
    fetch_nutrient_data()
