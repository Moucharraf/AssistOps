"""Check the n8n HTTP boundary using synthetic operations, without model calls."""

import time
from uuid import uuid4

import httpx


def wait_for_result(client, headers, receipt):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        response = client.post(
            "assistops/status", json={"receipt_id": receipt["receipt_id"]}, headers=headers
        )
        response.raise_for_status()
        job = response.json()
        if job["status"] in {"completed", "awaiting_approval"}:
            return job
        assert job["status"] != "failed"
        time.sleep(0.5)
    raise TimeoutError("n8n event was not processed")


def main():
    headers = {"X-AssistOps-Ingress-Key": "assistops-n8n-local-ingress-only"}
    payload = {
        "event_id": "n8n-check-" + uuid4().hex,
        "conversation_id": "n8n-check-" + uuid4().hex,
        "message": "Consulte ma facture synthétique INV-001.",
        "tool_call": {"name": "get_invoice", "invoice_id": "INV-001"},
    }
    with httpx.Client(base_url="http://127.0.0.1:5678/webhook/", timeout=20) as client:
        assert client.post("assistops/events", json=payload).status_code in {401, 403}
        for field in ("user_id", "tenant_id", "source", "decision"):
            response = client.post(
                "assistops/events", json={**payload, field: "forged"}, headers=headers
            )
            assert response.status_code == 422, response.status_code
        accepted = client.post("assistops/events", json=payload, headers=headers)
        assert accepted.status_code == 202, accepted.text
        receipt = accepted.json()
        replay = client.post("assistops/events", json=payload, headers=headers)
        assert replay.status_code == 202
        assert replay.json()["duplicate"]
        assert replay.json()["receipt_id"] == receipt["receipt_id"]
        conflict = client.post(
            "assistops/events", json={**payload, "message": "Changed"}, headers=headers
        )
        assert conflict.status_code == 409
        job = wait_for_result(client, headers, receipt)
        assert job["result"]["outcome"] == "read_completed", job["result"]
        missing = client.post(
            "assistops/status", json={"receipt_id": str(uuid4())}, headers=headers
        )
        assert missing.status_code == 404
        proposal = client.post(
            "assistops/events",
            headers=headers,
            json={
                **payload,
                "event_id": "n8n-ticket-" + uuid4().hex,
                "tool_call": {
                    "name": "create_ticket",
                    "invoice_id": "INV-001",
                    "subject": "Synthetic n8n integration check",
                    "description": "Fictional invoice dispute for automated testing.",
                },
            },
        )
        assert proposal.status_code == 202
        pending = wait_for_result(client, headers, proposal.json())
        assert pending["status"] == "awaiting_approval"
        assert pending["result"]["ticket_id"] is None
        # The ingress credential cannot impersonate the separate human reviewer.
        forged = client.post(
            "assistops/status",
            headers=headers,
            json={"receipt_id": proposal.json()["receipt_id"], "decision": "approved"},
        )
        assert forged.status_code == 422
        assert wait_for_result(client, headers, proposal.json())["status"] == "awaiting_approval"
    print("n8n: authentication, identity, signature, replay, status and approval boundary passed")


if __name__ == "__main__":
    main()
