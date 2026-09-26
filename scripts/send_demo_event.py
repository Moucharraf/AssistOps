"""Send a signed local demo event twice and verify its durable receipt."""

import argparse
import json
import time
from uuid import uuid4

import httpx
from demo_http import post

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--wait", action="store_true", help="Wait for the worker result")
parser.add_argument("--processor", choices=["demo", "rag"], default="demo")
args = parser.parse_args()


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
with httpx.Client(base_url="http://localhost:8000", timeout=15) as client:
    first = post(client, "/v1/events", body)
    second = post(client, "/v1/events", body)
    first.raise_for_status()
    second.raise_for_status()
    assert first.status_code == second.status_code == 202
    assert first.json()["receipt_id"] == second.json()["receipt_id"]
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    report = {"first": first.json(), "replay": second.json()}
    if args.wait:
        query = json.dumps(
            {
                "receipt_id": first.json()["receipt_id"],
                "tenant_id": "demo",
                "user_id": "user-001",
                "source": "webhook",
            }
        ).encode()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status = post(client, "/v1/events/status", query)
            status.raise_for_status()
            state = status.json()
            if state["status"] in ("completed", "failed"):
                assert state["status"] == "completed", state
                assert state["result"]["processor"] == args.processor
                assert state["result"]["business_action_executed"] is False
                if args.processor == "rag":
                    assert state["result"]["outcome"] == "answered", state["result"]["outcome"]
                    assert state["result"]["citations"]
                report["job"] = state
                break
            time.sleep(0.25)
        else:
            raise TimeoutError("Worker did not complete within 60 seconds")
    print(json.dumps(report, indent=2))
