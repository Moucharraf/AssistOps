"""Exercise the default local connector's HTTP rate limit without queuing jobs."""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
from demo_http import signed_headers


def main():
    body = json.dumps(
        {
            "tenant_id": "demo",
            "user_id": "user-001",
            "source": "webhook",
            "receipt_id": str(uuid4()),
        }
    ).encode()
    headers = signed_headers(body)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        # Looking up a nonexistent receipt exercises admission without starting any agent.
        def request(_):
            return client.post("/v1/events/status", content=body, headers=headers)

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(request, range(180)))
        assert all(response.status_code in (404, 429) for response in responses)
        limited = [response for response in responses if response.status_code == 429]
        assert limited, "Expected throttling with the default local limit (120 tokens / 60 s)"
        for response in limited:
            assert int(response.headers["Retry-After"]) >= 1
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json()["error"]["code"] == "rate_limited"
        assert client.get("/health/live").status_code == 200
    print(json.dumps({"status": "passed", "requests": len(responses), "throttled": len(limited)}))


if __name__ == "__main__":
    main()
