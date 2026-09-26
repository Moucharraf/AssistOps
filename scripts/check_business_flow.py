"""Exercise synthetic business operations over HTTP, including a simulated human decision."""

import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx


def post(client, path, payload):
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"assistops-local-webhook-secret-32-chars",
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    response = client.post(
        path,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-AssistOps-Connector": "demo",
            "X-AssistOps-Timestamp": timestamp,
            "X-AssistOps-Signature": "v1=" + signature,
        },
    )
    response.raise_for_status()
    return response.json()


def dispatch(client, call):
    payload = {
        "event_id": "business-demo-" + uuid4().hex,
        "tenant_id": "demo",
        "user_id": "user-001",
        "source": "webhook",
        "conversation_id": "business-demo",
        "message": "Vérification des opérations sur données synthétiques.",
        "tool_call": call,
    }
    receipt = post(client, "/v1/events", payload)
    duplicate = post(client, "/v1/events", payload)
    assert duplicate["duplicate"] and duplicate["receipt_id"] == receipt["receipt_id"]
    query = {key: payload[key] for key in ("tenant_id", "user_id", "source")}
    query["receipt_id"] = receipt["receipt_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = post(client, "/v1/events/status", query)
        if job["status"] in {"completed", "awaiting_approval"}:
            return query, job
        assert job["status"] != "failed", "Business worker failed"
        time.sleep(0.25)
    raise TimeoutError("Business worker did not complete")


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        for call in [{"name": "get_user"}, {"name": "get_invoice", "invoice_id": "INV-001"}]:
            _, job = dispatch(client, call)
            assert job["result"]["outcome"] == "read_completed"
            assert job["result"]["data"]["origin"] == "synthetic"
        _, denied = dispatch(client, {"name": "get_invoice", "invoice_id": "INV-002"})
        assert denied["result"]["outcome"] == "denied"
        for choice in ("approved", "rejected"):
            query, job = dispatch(
                client,
                {
                    "name": "create_ticket",
                    "invoice_id": "INV-001",
                    "subject": "Contestation synthétique",
                    "description": "Scénario automatique de test ; aucune donnée client réelle.",
                },
            )
            assert job["status"] == "awaiting_approval"
            assert job["result"]["ticket_id"] is None
            review = {
                "tenant_id": "demo",
                "user_id": "reviewer-001",
                "source": "webhook",
                "proposal_id": job["result"]["proposal"]["id"],
            }
            shown = post(client, "/v1/approvals/status", review)
            # Only this test script impersonates the separate demo reviewer automatically.
            decision = {
                **review,
                "decision": choice,
                "arguments_hash": shown["proposal"]["arguments_hash"],
            }
            answer = post(client, "/v1/approvals/decide", decision)
            replay = post(client, "/v1/approvals/decide", decision)
            assert answer == replay
            assert bool(answer["ticket_id"]) == (choice == "approved")
            saved = post(client, "/v1/events/status", query)
            assert saved["status"] == "completed" and saved["result"] == answer
    print(
        json.dumps(
            {
                "status": "passed",
                "origin": "synthetic",
                "paid_calls": 0,
                "checks": ["user", "invoice", "ownership", "approval", "rejection", "replay"],
            }
        )
    )


if __name__ == "__main__":
    main()
