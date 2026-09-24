CREATE TABLE inbound_events (
    id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    source text NOT NULL CHECK (source IN ('webhook', 'slack', 'email')),
    event_id text NOT NULL,
    payload_hash text NOT NULL,
    payload jsonb NOT NULL,
    connector_id text NOT NULL,
    correlation_id text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, source, event_id)
);

-- Durable inbox. A later worker will consume pending jobs; none are executed yet.
CREATE TABLE event_jobs (
    event_id uuid PRIMARY KEY REFERENCES inbound_events(id),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX event_jobs_pending ON event_jobs(created_at) WHERE status = 'pending';

CREATE TABLE event_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL REFERENCES inbound_events(id),
    action text NOT NULL,
    connector_id text NOT NULL,
    correlation_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
