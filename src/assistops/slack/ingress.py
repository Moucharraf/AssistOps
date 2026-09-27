"""Normalize only authenticated Socket Mode mentions from explicitly allowed identities."""

import hashlib
import re

from assistops.events import EventError, EventInput
from assistops.rate_limits import ConnectorRateLimiter
from assistops.storage import EventStore, connect

TIMESTAMP = re.compile(r"[0-9]{10,16}\.[0-9]{6}\Z")


def normalize(payload, slack, settings, bot_user_id):
    connector = slack.connector(settings)
    event = payload.get("event") or {}
    if not isinstance(event, dict):
        return None
    member = event.get("user")
    if (
        payload.get("type") != "event_callback"
        or payload.get("team_id") != slack.team_id
        or payload.get("is_ext_shared_channel")
        or event.get("type") != "app_mention"
        or event.get("channel") != slack.channel_id
        or not isinstance(member, str)
        or member not in slack.user_map
        or event.get("is_ext_shared_channel")
        or event.get("bot_id")
        or event.get("subtype")
        or event.get("hidden")
        or member == bot_user_id
    ):
        return None
    timestamp = event.get("ts", "")
    thread = event.get("thread_ts", timestamp)
    text = event.get("text", "")
    event_id = payload.get("event_id", "")
    if (
        not isinstance(text, str)
        or f"<@{bot_user_id}>" not in text
        or not isinstance(timestamp, str)
        or not TIMESTAMP.fullmatch(timestamp)
        or not isinstance(thread, str)
        or not TIMESTAMP.fullmatch(thread)
        or not isinstance(event_id, str)
        or not re.fullmatch(r"Ev[A-Za-z0-9]+", event_id)
    ):
        return None
    message = text.replace(f"<@{bot_user_id}>", "", 1).strip()
    # Slack renders these entities as literal characters in message text.
    message = message.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    conversation = hashlib.sha256(
        f"{slack.team_id}:{slack.channel_id}:{member}:{thread}".encode()
    ).hexdigest()
    event_input = EventInput(
        tenant_id=connector.tenant_id,
        source="slack",
        user_id=slack.user_map[member],
        event_id=f"{slack.team_id}_{event_id}",
        conversation_id="slack_" + conversation,
        message=message,
    )
    return event_input, member, thread


def accept(payload, slack, settings, bot_user_id):
    normalized = normalize(payload, slack, settings, bot_user_id)
    if normalized is None:
        return None
    event, member, thread = normalized
    retry = ConnectorRateLimiter(settings).consume(slack.connector_id, slack.connector(settings))
    if retry is not None:
        raise EventError(429, "slack_rate_limited", retry_after=retry)
    with connect(settings) as connection:
        receipt = EventStore(settings).accept(
            event, slack.connector_id, "slack_" + payload["event_id"], connection=connection
        )
        row = connection.execute(
            """INSERT INTO slack_replies (event_id, team_id, channel_id, slack_user_id, thread_ts)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING RETURNING event_id""",
            (receipt.receipt_id, slack.team_id, slack.channel_id, member, thread),
        ).fetchone()
        if row is None:
            saved = connection.execute(
                """SELECT team_id, channel_id, slack_user_id, thread_ts
                   FROM slack_replies WHERE event_id = %s""",
                (receipt.receipt_id,),
            ).fetchone()
            if saved != (slack.team_id, slack.channel_id, member, thread):
                raise EventError(409, "slack_destination_conflict")
    return receipt
