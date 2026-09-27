-- The inbox event and its immutable Slack destination commit before Socket Mode acknowledgement.
CREATE TABLE slack_replies (
    event_id uuid PRIMARY KEY REFERENCES inbound_events(id),
    team_id text NOT NULL,
    channel_id text NOT NULL,
    slack_user_id text NOT NULL,
    thread_ts text NOT NULL,
    message_ts text,
    response_hash text,
    state text NOT NULL DEFAULT 'waiting'
        CHECK (state IN ('waiting', 'sending', 'complete', 'uncertain', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    error_code text,
    started_at timestamptz,
    next_run_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX slack_replies_pending ON slack_replies(next_run_at) WHERE state = 'waiting';
