import requests
import json
import time
import os

def fetch_blocks():
    api_url = "https://soilhealth4.dac.gov.in/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # The GraphQL query you discovered earlier for fetching blocks
    block_query = """
    query GetBlocks($getBlocksId: String, $name: String, $code: String, $state: ID, $district: ID, $subdistrict: ID, $aspirationalblock: Boolean) {
      getBlocks(
        id: $getBlocksId
        name: $name
        code: $code
        state: $state
        district: $district
        subdistrict: $subdistrict
        aspirationalblock: $aspirationalblock
      )
    }
    """

    # 1. Load the Districts file we just made
    if not os.path.exists("india_districts_map.json"):
        print("Error: Could not find india_districts_map.json!")
        return

    with open("india_districts_map.json", "r") as f:
        master_map = json.load(f)

    print("Loaded districts map. Beginning block extraction...\n")

    # 2. Iterate through states and their districts
    for state_name, state_data in master_map.items():
        state_id = state_data.get("state_id")
        districts = state_data.get("districts", {})
        
        print(f"\n--- Processing State: {state_name} ---")

        for dist_name, dist_id in districts.items():
            print(f"  Fetching blocks for District: {dist_name}...")
            
            # If the districts dictionary already contains a dictionary instead of a string,
            # it means we already ran this. Let's handle string IDs vs complex objects.
            if isinstance(dist_id, dict):
                actual_dist_id = dist_id.get("id")
            else:
                actual_dist_id = dist_id
                
            # Upgrade the map structure to hold blocks
            master_map[state_name]["districts"][dist_name] = {
                "id": actual_dist_id,
                "blocks": {}
            }

            # 3. Construct the payload using BOTH State ID and District ID
            payload = {
                "operationName": "GetBlocks",
                "query": block_query,
                "variables": {
                    "state": state_id,
                    "district": actual_dist_id
                }
            }

            # 4. Make the request
            response = requests.post(api_url, json=payload, headers=headers)
            
            if response.status_code == 200:
                raw_blocks = response.json().get("data", {}).get("getBlocks", [])
                
                if isinstance(raw_blocks, str):
                    try:
                        raw_blocks = json.loads(raw_blocks)
                    except json.JSONDecodeError:
                        raw_blocks = []
                
                # 5. Save the block names and IDs into our map
                count = 0
                for block in raw_blocks:
                    block_name = block.get("name")
                    block_id = block.get("_id")
                    if block_name and block_id:
                        master_map[state_name]["districts"][dist_name]["blocks"][block_name] = block_id
                        count += 1
                
                print(f"    -> Found {count} blocks.")
            else:
                print(f"    -> FAILED. Status Code: {response.status_code}")

            # 6. Save the map incrementally. 
            # Because there are hundreds of districts, saving after each one is crucial.
            with open("india_blocks_map.json", "w") as f:
                json.dump(master_map, f, indent=4)

            # 7. CRITICAL: Wait 2 seconds. Do not lower this.
            # Hitting an API for every district in India back-to-back will trigger firewalls.
            time.sleep(2)

    print("\nSuccess! All blocks have been saved to 'india_blocks_map.json'.")

if __name__ == "__main__":
    fetch_blocks()
