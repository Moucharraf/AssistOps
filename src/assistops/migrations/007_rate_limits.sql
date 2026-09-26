CREATE TABLE connector_rate_limits (
    connector_id text NOT NULL,
    tenant_id text NOT NULL,
    source text NOT NULL,
    tokens numeric NOT NULL CHECK (tokens >= 0),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (connector_id, tenant_id, source)
);
