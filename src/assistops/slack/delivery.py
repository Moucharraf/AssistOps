"""Durable notification state; an ambiguous initial post is never blindly repeated."""

import hashlib
import json

import structlog
from psycopg.rows import dict_row

from assistops.jobs import audit
from assistops.slack.messages import render
from assistops.slack.transport import SlackError
from assistops.storage import connect

logger = structlog.get_logger()


def claim(settings, slack):
    connector = slack.connector(settings)
    with connect(settings) as connection, connection.cursor(row_factory=dict_row) as cursor:
        stale = connection.execute(
            """UPDATE slack_replies SET state = 'uncertain', error_code = 'sender_interrupted',
               updated_at = clock_timestamp() WHERE state = 'sending'
               AND started_at < clock_timestamp() - interval '2 minutes'
               AND team_id = %s AND channel_id = %s RETURNING event_id""",
            (slack.team_id, slack.channel_id),
        ).fetchall()
        for (event_id,) in stale:
            audit(connection, event_id, "slack_reply_uncertain", {"error": "sender_interrupted"})
        row = cursor.execute(
            """SELECT s.*, j.status, j.result, e.payload->>'user_id' AS user_id,
                      (p.status = 'pending' AND p.expires_at <= clock_timestamp()) AS expired
               FROM slack_replies s JOIN event_jobs j ON j.event_id = s.event_id
               JOIN inbound_events e ON e.id = s.event_id
               LEFT JOIN ticket_proposals p ON p.event_id = s.event_id
               WHERE s.state = 'waiting' AND s.next_run_at <= clock_timestamp()
                 AND s.team_id = %s AND s.channel_id = %s AND e.tenant_id = %s
                 AND e.connector_id = %s AND e.source = 'slack'
                 AND j.status NOT IN ('pending', 'processing')
               ORDER BY s.next_run_at, s.event_id LIMIT 1 FOR UPDATE OF s SKIP LOCKED""",
            (slack.team_id, slack.channel_id, connector.tenant_id, slack.connector_id),
        ).fetchone()
        if row is None:
            return None
        if slack.user_map.get(row["slack_user_id"]) != row["user_id"]:
            connection.execute(
                """UPDATE slack_replies SET state = 'failed', error_code = 'identity_revoked'
                   WHERE event_id = %s""",
                (row["event_id"],),
            )
            audit(connection, row["event_id"], "slack_reply_failed", {"error": "identity_revoked"})
            return None
        body = render(row, slack)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if digest == row["response_hash"]:
            connection.execute(
                """UPDATE slack_replies SET next_run_at = clock_timestamp() + interval '15 seconds'
                   WHERE event_id = %s""",
                (row["event_id"],),
            )
            return None
        connection.execute(
            """UPDATE slack_replies SET state = 'sending', started_at = clock_timestamp(),
               attempts = attempts + 1, updated_at = clock_timestamp() WHERE event_id = %s""",
            (row["event_id"],),
        )
    return row, body, digest


def deliver_once(settings, slack, client):
    delivery = claim(settings, slack)
    if delivery is None:
        return False
    row, body, digest = delivery
    try:
        message_ts = client.send(row, body)
    except SlackError as exc:
        state = "uncertain" if exc.uncertain else "failed"
        if exc.retry_after is not None and row["attempts"] < 4:
            state = "waiting"
        with connect(settings) as connection:
            connection.execute(
                """UPDATE slack_replies SET state = %s, error_code = %s,
                   next_run_at = clock_timestamp() + %s * interval '1 second',
                   updated_at = clock_timestamp() WHERE event_id = %s AND state = 'sending'""",
                (state, exc.code, exc.retry_after or 0, row["event_id"]),
            )
            audit(connection, row["event_id"], "slack_reply_" + state, {"error": exc.code})
        logger.warning("slack_reply_failed", event_id=str(row["event_id"]), error_code=exc.code)
        return True
    terminal = row["status"] in {"completed", "failed"} or row["expired"]
    with connect(settings) as connection:
        connection.execute(
            """UPDATE slack_replies SET state = %s, message_ts = %s, response_hash = %s,
               attempts = 0, error_code = NULL,
               next_run_at = clock_timestamp() + interval '5 seconds',
               updated_at = clock_timestamp() WHERE event_id = %s AND state = 'sending'""",
            ("complete" if terminal else "waiting", message_ts, digest, row["event_id"]),
        )
        audit(
            connection,
            row["event_id"],
            "slack_reply_updated" if row["message_ts"] else "slack_reply_posted",
            {"channel_id": row["channel_id"], "message_ts": message_ts},
        )
    logger.info("slack_reply_saved", event_id=str(row["event_id"]), terminal=bool(terminal))
    return True
