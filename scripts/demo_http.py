"""Signed HTTP helpers for the public local demo connector."""

import hashlib
import hmac
import time


def signed_headers(body):
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"assistops-local-webhook-secret-32-chars",
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-AssistOps-Connector": "demo",
        "X-AssistOps-Timestamp": timestamp,
        "X-AssistOps-Signature": "v1=" + signature,
    }


def post(client, path, body):
    deadline = time.monotonic() + 30
    for attempt in range(5):
        # Retry the same bytes with a fresh signature, preserving event idempotency.
        response = client.post(path, content=body, headers=signed_headers(body))
        if response.status_code != 429:
            return response
        delay = int(response.headers["Retry-After"])
        if attempt == 4 or not 1 <= delay <= deadline - time.monotonic():
            return response
        time.sleep(delay)
    return response
