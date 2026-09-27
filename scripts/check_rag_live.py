"""Explicit paid smoke checks against the local RAG stack and synthetic corpus."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from demo_http import post


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="Explicitly invoke paid generation; never used in CI",
    )
    parser.add_argument("--output", type=Path, default=Path(".cache/rag-live.json"))
    args = parser.parse_args()
    benchmark = json.loads(Path("data/evaluation/reference.json").read_text(encoding="utf-8"))
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "origin": "synthetic",
        "scope": "three live smoke checks, not an independent quality benchmark",
        "cases": [],
    }
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        for question in benchmark["questions"]:
            if question["id"] not in {"Q01", "Q17", "Q19"}:
                continue
            body = json.dumps(
                {
                    "event_id": "rag-smoke-" + uuid4().hex,
                    "conversation_id": "rag-smoke",
                    "tenant_id": "demo",
                    "user_id": "user-001",
                    "source": "webhook",
                    "message": question["question"],
                }
            ).encode()
            response = post(client, "/v1/events", body)
            response.raise_for_status()
            receipt = response.json()["receipt_id"]
            query = json.dumps(
                {
                    "receipt_id": receipt,
                    "tenant_id": "demo",
                    "user_id": "user-001",
                    "source": "webhook",
                }
            ).encode()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                response = post(client, "/v1/events/status", query)
                response.raise_for_status()
                state = response.json()
                if state["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.5)
            else:
                raise TimeoutError("RAG smoke check timed out")
            answer = state.get("result") or {}
            expected = "answered" if question["id"] == "Q01" else "abstained"
            passed = state["status"] == "completed" and answer.get("outcome") == expected
            if question["id"] == "Q01":
                passed = passed and any(
                    c["document"] == "billing-disputes@2" for c in answer.get("citations", [])
                )
            report["cases"].append(
                {
                    "question_id": question["id"],
                    "expected_outcome": expected,
                    "passed": bool(passed),
                    "result": answer,
                }
            )
            # Persist partial evidence even if a later request fails.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print(
        json.dumps(
            {
                "cases": [{"id": c["question_id"], "passed": c["passed"]} for c in report["cases"]],
                "report": str(args.output),
            }
        )
    )
    return 0 if all(c["passed"] for c in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
