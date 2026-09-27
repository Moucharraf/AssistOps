"""Exercise synthetic business operations over HTTP, including a simulated human decision."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
from demo_http import post as signed_post


def post(client, path, payload):
    body = json.dumps(payload).encode()
    response = signed_post(client, path, body)
    response.raise_for_status()
    return response.json()


def dispatch(
    client,
    call=None,
    message="Vérification des opérations sur données synthétiques.",
    *,
    conversation_id=None,
):
    payload = {
        "event_id": "business-demo-" + uuid4().hex,
        "tenant_id": "demo",
        "user_id": "user-001",
        "source": "webhook",
        "conversation_id": conversation_id or "business-demo-" + uuid4().hex,
        "message": message,
    }
    if call is not None:
        payload["tool_call"] = call
    receipt = post(client, "/v1/events", payload)
    duplicate = post(client, "/v1/events", payload)
    assert duplicate["duplicate"] and duplicate["receipt_id"] == receipt["receipt_id"]
    query = {key: payload[key] for key in ("tenant_id", "user_id", "source")}
    query["receipt_id"] = receipt["receipt_id"]
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        job = post(client, "/v1/events/status", query)
        if job["status"] in {"completed", "awaiting_approval"}:
            return query, job
        assert job["status"] != "failed", "Business worker failed"
        time.sleep(0.25)
    raise TimeoutError("Business worker did not complete")


def check_decision(client, query, job, choice):
    assert job["status"] == "awaiting_approval", job["result"].get("outcome")
    assert job["result"]["ticket_id"] is None
    if "ticket_target" in job["result"]["proposal"]["arguments"]:
        raise RuntimeError("Demo scripts must never approve real external ticket creation")
    review = {
        "tenant_id": "demo",
        "user_id": "reviewer-001",
        "source": "webhook",
        "proposal_id": job["result"]["proposal"]["id"],
    }
    shown = post(client, "/v1/approvals/status", review)
    # Only this test script impersonates the separate demo reviewer automatically.
    decision = {**review, "decision": choice, "arguments_hash": shown["proposal"]["arguments_hash"]}
    answer = post(client, "/v1/approvals/decide", decision)
    replay = post(client, "/v1/approvals/decide", decision)
    assert answer == replay
    assert bool(answer["ticket_id"]) == (choice == "approved")
    saved = post(client, "/v1/events/status", query)
    assert saved["status"] == "completed" and saved["result"] == answer
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    paid = parser.add_mutually_exclusive_group()
    paid.add_argument(
        "--natural-ticket",
        action="store_true",
        help="Paid routing check; requires the supervisor worker",
    )
    paid.add_argument(
        "--memory",
        action="store_true",
        help="Three paid routing calls: invoice, follow-up ticket, confirmation without approval",
    )
    args = parser.parse_args()
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        if args.memory:
            conversation = "memory-demo-" + uuid4().hex
            _, first = dispatch(
                client,
                message="Consulte le montant de la facture INV-001.",
                conversation_id=conversation,
            )
            assert first["result"]["outcome"] == "read_completed"
            assert first["result"]["supervisor"]["context_turns"] == 0
            query, pending = dispatch(
                client,
                message="Prépare un ticket pour cette facture : une ligne est incorrecte.",
                conversation_id=conversation,
            )
            assert pending["status"] == "awaiting_approval"
            assert pending["result"]["proposal"]["arguments"]["invoice_id"] == "INV-001"
            assert pending["result"]["supervisor"]["context_turns"] == 1
            _, confirmation = dispatch(client, message="Oui.", conversation_id=conversation)
            assert confirmation["result"]["outcome"] == "clarification_required"
            assert confirmation["result"]["reason"] in {
                "unsupported",
                "ambiguous",
                "approval_pending",
            }
            assert post(client, "/v1/events/status", query)["status"] == "awaiting_approval"
            answer = check_decision(client, query, pending, "approved")
            usage = [
                job["result"]["supervisor"]["routing_usage"]
                for job in (first, pending, confirmation)
            ]
            report = {
                "status": "passed",
                "origin": "synthetic",
                "routing_usage": usage,
                "estimated_cost_usd": sum(item["estimated_cost_usd"] for item in usage),
                "result": answer,
            }
            output = Path(".cache/memory-smoke.json")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "report": str(output),
                        "estimated_cost_usd": report["estimated_cost_usd"],
                    }
                )
            )
            return
        if args.natural_ticket:
            query, job = dispatch(
                client,
                message=(
                    "Consulte le montant et le statut de la facture INV-001, "
                    "puis prépare un ticket pour contester une ligne incorrecte."
                ),
            )
            assert job["result"]["processor"] == "supervisor"
            assert job["result"]["supervisor"]["steps"] == ["read", "propose"]
            answer = check_decision(client, query, job, "approved")
            output = Path(".cache/supervisor-smoke.json")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "origin": "synthetic",
                        "routing_usage": answer["supervisor"]["routing_usage"],
                        "report": str(output),
                    }
                )
            )
            return
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
            check_decision(client, query, job, choice)
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
