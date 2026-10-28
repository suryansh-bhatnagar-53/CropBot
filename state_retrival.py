import requests
import json

def fetch_and_save_states():
    api_url = "https://soilhealth4.dac.gov.in/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    state_query = """
    query GetState($getStateId: String, $code: String) {
      getState(id: $getStateId, code: $code)
    }
    """

    payload = {
        "operationName": "GetState",
        "query": state_query,
        "variables": {}
    }

    print("Fetching States from server...")
    response = requests.post(api_url, json=payload, headers=headers)

    if response.status_code == 200:
        # Extract the raw list from the GraphQL response
        raw_states = response.json().get("data", {}).get("getState", [])
        
        # Handle GraphQL sometimes returning stringified JSON
        if isinstance(raw_states, str):
            raw_states = json.loads(raw_states)
            
        print(f"Success! Found {len(raw_states)} states.")

        # Reformat into a clean dictionary where the State Name is the key
        states_dict = {}
        for state in raw_states:
            name = state.get("name")
            state_id = state.get("_id")
            if name and state_id:
                states_dict[name] = state_id

        # Save it to a file
        filename = "india_states_map.json"
        with open(filename, "w") as f:
            json.dump(states_dict, f, indent=4)
            
        print(f"Saved cleanly to {filename}")
        
    else:
        print(f"Failed to fetch. Status code: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    fetch_and_save_states()
