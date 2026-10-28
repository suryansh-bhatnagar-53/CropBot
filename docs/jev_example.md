```bash
curl https://api.beatapi.io/v1/systemone \
  -X POST \
  -H "Authorization: Bearer $BEATAPI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "jev-1.14-free",
    "state": "A user asks whether this action is safe: deleting temporary files.",
    "questions": {
      "safe": {
        "type": "noul",
        "instructions": "Is this action safe?",
        "criteria": {
          "true": "The action is safe and reversible.",
          "false": "The action is risky or irreversible."
        }
      }
    }
  }'
```
