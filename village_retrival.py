import requests
import json
import time
import os

def fetch_villages():
    api_url = "https://soilhealth4.dac.gov.in/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # The exact Village query you found
    village_query = """
    query GetVillageBydistrict($getVillageBydistrictId: String, $name: String, $state: String, $district: ID, $subdistrict: String, $block: String, $code: String) {
      getVillageBydistrict(
        id: $getVillageBydistrictId
        name: $name
        state: $state
        district: $district
        subdistrict: $subdistrict
        block: $block
        code: $code
      )
    }
    """ 
    
    # 1. Load the Blocks file we just made
    if not os.path.exists("india_blocks_map.json"):
        print("Error: Could not find india_blocks_map.json!")
        return

    with open("india_blocks_map.json", "r") as f:
        master_map = json.load(f)

    print("Loaded blocks map. Beginning village extraction...\n")
    print("WARNING: There are ~600,000 villages in India. This will take a long time to finish.\n")

    # 2. Iterate through States -> Districts -> Blocks
    for state_name, state_data in master_map.items():
        state_id = state_data.get("state_id")
        districts = state_data.get("districts", {})
        
        for dist_name, dist_data in districts.items():
            
            # --- SAFEGUARD: Skip if Level 3 didn't finish this district ---
            if isinstance(dist_data, str):
                print(f"Skipping {dist_name} - No blocks found in map (Run Level 3 again).")
                continue 
            
            dist_id = dist_data.get("id")
            blocks = dist_data.get("blocks", {})
            
            for block_name, block_id in blocks.items():
                print(f"Fetching villages for Block: {block_name} ({dist_name}, {state_name})...")
                
                # Upgrade the map structure to hold villages
                if isinstance(block_id, dict):
                    actual_block_id = block_id.get("id")
                else:
                    actual_block_id = block_id
                    
                master_map[state_name]["districts"][dist_name]["blocks"][block_name] = {
                    "id": actual_block_id,
                    "villages": {}
                }

                # 3. Construct the payload using State, District, and Block IDs
                payload = {
                    "operationName": "GetVillageBydistrict", # <--- FIXED
                    "query": village_query,
                    "variables": {
                        "state": state_id,
                        "district": dist_id,
                        "block": actual_block_id
                    }
                }

                # 4. Make the request
                response = requests.post(api_url, json=payload, headers=headers)
                
                if response.status_code == 200:
                    # Update JSON key to match the new query response
                    raw_villages = response.json().get("data", {}).get("getVillageBydistrict", []) # <--- FIXED
                    
                    if isinstance(raw_villages, str):
                        try:
                            raw_villages = json.loads(raw_villages)
                        except json.JSONDecodeError:
                            raw_villages = []
                    
                    # 5. Save the village names and IDs
                    count = 0
                    for village in raw_villages:
                        vil_name = village.get("name")
                        vil_id = village.get("_id")
                        if vil_name and vil_id:
                            master_map[state_name]["districts"][dist_name]["blocks"][block_name]["villages"][vil_name] = vil_id
                            count += 1
                    
                    print(f"  -> Found {count} villages.")
                else:
                    print(f"  -> FAILED. Status Code: {response.status_code}")

                # 6. Save incrementally after EVERY block.
                with open("india_villages_map.json", "w") as f:
                    json.dump(master_map, f, indent=4)

                # 7. RATE LIMITING: Do not skip this!
                time.sleep(2)

    print("\nSuccess! The ultimate master map has been saved to 'india_villages_map.json'.")

if __name__ == "__main__":
    fetch_villages()
