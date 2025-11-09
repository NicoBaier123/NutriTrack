from __future__ import annotations

import http.client
import json

from fastapi import HTTPException


def _post_meal_ingest(items, day_str: str, input_text: str):
    """
    Post meal ingestion payload to the local API.
    """
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
    payload = json.dumps(
        {
            "day": day_str,
            "source": "chat",
            "input_text": input_text,
            "items": [
                {"food_name": item["name"], "grams": float(item["grams"])}
                for item in items
                if item.get("name") and item.get("grams")
            ],
        }
    )
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/meals/ingest", body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    try:
        parsed = json.loads(data) if data else {}
    except Exception:
        parsed = {"raw": data}

    if resp.status >= 300:
        raise HTTPException(status_code=resp.status, detail=parsed or data)
    return parsed

