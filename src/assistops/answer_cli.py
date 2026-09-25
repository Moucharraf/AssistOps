"""Answer one question with server-configured identity and the shared daily budget."""

import argparse
import asyncio
import json
from uuid import uuid4

from assistops.config import Settings
from assistops.events import EventInput
from assistops.rag_agent import RagProcessor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--user", required=True)
    args = parser.parse_args()
    event = EventInput(
        event_id="cli-" + uuid4().hex,
        conversation_id="cli",
        tenant_id=args.tenant,
        user_id=args.user,
        source="webhook",
        message=args.question,
    )
    answer = asyncio.run(RagProcessor(Settings())(event))
    print(json.dumps(answer, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
