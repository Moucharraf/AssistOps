import runpy
from pathlib import Path
from unittest.mock import Mock

import httpx

post = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "demo_http.py"))["post"]


def test_throttled_demo_retries_identical_body_with_fresh_signature(monkeypatch):
    monkeypatch.setattr("time.time", Mock(side_effect=[1000, 1002]))
    sleep = Mock()
    monkeypatch.setattr("time.sleep", sleep)
    client = Mock()
    client.post.side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(202),
    ]
    body = b'{"event_id":"same-event"}'
    assert post(client, "/v1/events", body).status_code == 202
    first, second = [call.kwargs for call in client.post.call_args_list]
    assert first["content"] == second["content"] == body
    assert first["headers"]["X-AssistOps-Signature"] != second["headers"]["X-AssistOps-Signature"]
    sleep.assert_called_once_with(2)


def test_demo_retry_wait_is_bounded(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("time.sleep", sleep)
    client = Mock()
    client.post.return_value = httpx.Response(429, headers={"Retry-After": "3600"})
    assert post(client, "/v1/events", b"{}").status_code == 429
    client.post.assert_called_once()
    sleep.assert_not_called()
