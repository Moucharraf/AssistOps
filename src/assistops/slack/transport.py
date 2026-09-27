"""Slack Web API transport with no redirects or implicit message retries."""

import httpx

from assistops.slack.ingress import TIMESTAMP


class SlackError(Exception):
    def __init__(self, code, *, uncertain=False, retry_after=None):
        super().__init__(code)
        self.code, self.uncertain, self.retry_after = code, uncertain, retry_after


class SlackAPI:
    def __init__(self, slack, *, transport=None):
        self.client = httpx.Client(
            base_url="https://slack.com/api/",
            timeout=10,
            follow_redirects=False,
            headers={"Authorization": "Bearer " + slack.bot_token.get_secret_value()},
            transport=transport,
        )

    def close(self):
        self.client.close()

    def call(self, method, body):
        try:
            response = self.client.post(method, json=body)
        except httpx.HTTPError:
            raise SlackError("slack_transport_error", uncertain=True) from None
        if response.status_code == 429:
            raw = response.headers.get("Retry-After", "60")
            delay = int(raw) if raw.isdigit() and len(raw) < 6 else 3600
            raise SlackError("slack_rate_limited", retry_after=max(1, delay))
        if response.status_code != 200:
            raise SlackError("slack_http_error", uncertain=response.status_code >= 500)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            raise SlackError("slack_invalid_response", uncertain=True) from None
        if data.get("ok") is not True:
            error = data.get("error")
            known = {
                "invalid_auth",
                "token_revoked",
                "not_in_channel",
                "channel_not_found",
                "missing_scope",
                "is_archived",
                "message_not_found",
            }
            code = error if isinstance(error, str) and error in known else "api_error"
            # Slack can return an internal error after committing a write.
            raise SlackError("slack_" + code, uncertain=code == "api_error")
        return data

    def send(self, row, body):
        payload = {**body, "channel": row["channel_id"]}
        if row["message_ts"]:
            payload["ts"] = row["message_ts"]
            method = "chat.update"
        else:
            payload.update(
                thread_ts=row["thread_ts"],
                client_msg_id=str(row["event_id"]),
                unfurl_links=False,
                unfurl_media=False,
            )
            method = "chat.postMessage"
        result = self.call(method, payload)
        ts = result.get("ts", "")
        if (
            not isinstance(ts, str)
            or not TIMESTAMP.fullmatch(ts)
            or result.get("channel") != row["channel_id"]
            or (row["message_ts"] and ts != row["message_ts"])
        ):
            raise SlackError("slack_invalid_destination", uncertain=True)
        return ts
