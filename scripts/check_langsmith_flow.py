"""Verify receipt-scoped, content-free traces on the configured LangSmith server."""

import argparse
import json
import time
from uuid import uuid4

import httpx
from demo_http import post
from langsmith import Client

from assistops.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Export and read real telemetry")
    parser.add_argument("--natural", action="store_true", help="Exercise paid Supervisor routing")
    parser.add_argument(
        "--rag", action="store_true", help="Exercise paid routing and RAG generation"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required to contact the configured server")
    settings = Settings()
    expected = {"worker", "tools"}
    payload = {
        "event_id": "tracing-check-" + uuid4().hex,
        "conversation_id": "tracing-check-" + uuid4().hex,
        "tenant_id": "demo",
        "user_id": "user-001",
        "source": "webhook",
        "message": "Consulte le montant de la facture INV-001.",
    }
    if args.rag:
        payload["message"] = "Quelle est la procédure pour contester une facture ?"
        expected = {"worker", "supervisor", "route", "rag", "retrieve", "generation"}
    elif args.natural:
        expected |= {"supervisor", "route", "generation"}
    else:
        payload["tool_call"] = {"name": "get_invoice", "invoice_id": "INV-001"}

    def send(client, path, data):
        response = post(client, path, json.dumps(data).encode())
        response.raise_for_status()
        return response.json()

    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        receipt = send(client, "/v1/events", payload)
        query = {k: payload[k] for k in ("tenant_id", "user_id", "source")}
        query["receipt_id"] = receipt["receipt_id"]
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            job = send(client, "/v1/events/status", query)
            if job["status"] == "completed":
                break
            assert job["status"] not in {"failed", "awaiting_approval"}
            time.sleep(1)
        else:
            raise TimeoutError("Worker did not complete")
        assert job["result"]["outcome"] in {"read_completed", "answered", "abstained"}

    smith = Client(
        api_url=settings.langsmith_endpoint,
        api_key=settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else "",
        auto_batch_tracing=False,
    )
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            runs = list(
                smith.list_runs(
                    project_name=settings.langsmith_project,
                    filter='and(eq(metadata_key, "event_id"), eq(metadata_value, '
                    + json.dumps(receipt["receipt_id"])
                    + "))",
                    limit=30,
                )
            )
            if expected <= {run.name for run in runs}:
                break
            time.sleep(2)
        else:
            raise TimeoutError("Expected LangSmith spans were not received")
        assert len({run.trace_id for run in runs}) == 1
        for run in runs:
            assert not run.inputs and not run.outputs
            assert run.extra.get("metadata", {}).get("redaction_policy") == "metrics-only-v1"
            encoded = json.dumps(run.extra)
            assert payload["message"] not in encoded
            assert "INV-001" not in encoded and "user-001" not in encoded
        root = next(run for run in runs if run.parent_run_id is None)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "project": settings.langsmith_project,
                    "spans": sorted(run.name for run in runs),
                    "trace_url": smith.get_run_url(
                        run=root, project_name=settings.langsmith_project
                    ),
                    "content_redacted": True,
                }
            )
        )
    finally:
        smith.session.close()


if __name__ == "__main__":
    main()
