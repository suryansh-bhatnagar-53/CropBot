import requests
import json
import time
import os

def fetch_districts():
    api_url = "https://soilhealth4.dac.gov.in/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # The GraphQL query to get districts
    district_query = """
    query GetdistrictAndSubdistrictBystate($getdistrictAndSubdistrictBystateId: String, $name: String, $state: ID, $subdistrict: Boolean, $code: String, $aspirationaldistrict: Boolean) {
      getdistrictAndSubdistrictBystate(
        id: $getdistrictAndSubdistrictBystateId
        name: $name
        state: $state
        subdistrict: $subdistrict
        code: $code
        aspirationaldistrict: $aspirationaldistrict
      )
    }
    """

    # 1. Load the States file we just made
    if not os.path.exists("india_states_map.json"):
        print("Error: Could not find states_master.json!")
        return

    with open("india_states_map.json", "r") as f:
        states_dict = json.load(f)

    print(f"Loaded {len(states_dict)} states. Beginning district extraction...\n")

    # 2. Set up our master mapping dictionary
    # We will build this up and save it as we go
    india_geo_map = {}

    for state_name, state_id in states_dict.items():
        print(f"Fetching districts for: {state_name}...")
        
        # Initialize the state in our new map
        india_geo_map[state_name] = {
            "state_id": state_id,
            "districts": {}
        }

        # 3. Construct the payload using the current State ID
        payload = {
            "operationName": "GetdistrictAndSubdistrictBystate",
            "query": district_query,
            "variables": {"state": state_id}
        }

        # 4. Make the request
        response = requests.post(api_url, json=payload, headers=headers)
        
        if response.status_code == 200:
            raw_districts = response.json().get("data", {}).get("getdistrictAndSubdistrictBystate", [])
            
            # Handle GraphQL stringified JSON quirk
            if isinstance(raw_districts, str):
                try:
                    raw_districts = json.loads(raw_districts)
                except json.JSONDecodeError:
                    raw_districts = []
            
            # 5. Save the district names and IDs into our map
            count = 0
            for dist in raw_districts:
                dist_name = dist.get("name")
                dist_id = dist.get("_id")
                if dist_name and dist_id:
                    india_geo_map[state_name]["districts"][dist_name] = dist_id
                    count += 1
            
            print(f"  -> Found {count} districts.")
        else:
            print(f"  -> FAILED to fetch {state_name}. Status Code: {response.status_code}")

        # 6. Save the map to a file AFTER EVERY STATE.
        # This is your safety net!
        with open("india_districts_map.json", "w") as f:
            json.dump(india_geo_map, f, indent=4)

        # 7. CRITICAL: Wait 2 seconds before asking for the next state
        time.sleep(2)

    print("\nSuccess! All districts have been saved to 'india_districts_map.json'.")

if __name__ == "__main__":
    fetch_districts()
