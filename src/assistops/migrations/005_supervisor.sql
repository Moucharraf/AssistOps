-- A routing decision is immutable per event, including across worker retries.
CREATE TABLE supervisor_plans (
    event_id uuid PRIMARY KEY REFERENCES inbound_events(id),
    plan jsonb NOT NULL,
    access_fingerprint text NOT NULL,
    usage jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
