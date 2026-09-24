"""Send a signed local demo event twice and verify its durable receipt."""

import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx

body = json.dumps(
    {
        "event_id": "demo-" + uuid4().hex,
        "tenant_id": "demo",
        "user_id": "user-001",
        "conversation_id": "conversation-demo",
        "source": "webhook",
        "message": "Comment contester ma facture INV-001 ?",
    }
).encode()
timestamp = str(int(time.time()))
signature = hmac.new(
    b"assistops-local-webhook-secret-32-chars", timestamp.encode() + b"." + body, hashlib.sha256
).hexdigest()
headers = {
    "Content-Type": "application/json",
    "X-AssistOps-Connector": "demo",
    "X-AssistOps-Timestamp": timestamp,
    "X-AssistOps-Signature": "v1=" + signature,
}
with httpx.Client(base_url="http://localhost:8000", timeout=15) as client:
    first = client.post("/v1/events", content=body, headers=headers)
    second = client.post("/v1/events", content=body, headers=headers)
    first.raise_for_status()
    second.raise_for_status()
    assert first.status_code == second.status_code == 202
    assert first.json()["receipt_id"] == second.json()["receipt_id"]
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    print(json.dumps({"first": first.json(), "replay": second.json()}, indent=2))
