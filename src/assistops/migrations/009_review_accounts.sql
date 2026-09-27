-- Accounts are provisioned by an operator; web clients cannot assign identities or scopes.
CREATE TABLE review_accounts (
    username text PRIMARY KEY,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    connector_ids text[] NOT NULL CHECK (cardinality(connector_ids) > 0),
    password_hash text NOT NULL,
    disabled boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE review_sessions (
    token_hash text PRIMARY KEY,
    username text NOT NULL REFERENCES review_accounts(username) ON DELETE CASCADE,
    csrf_token text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX review_sessions_username_idx ON review_sessions(username);
CREATE INDEX review_sessions_expiry_idx ON review_sessions(expires_at);

-- Fixed windows are shared by every API process; keys contain hashed account/IP identifiers.
CREATE TABLE review_rate_limits (
    key text PRIMARY KEY,
    attempts integer NOT NULL,
    expires_at timestamptz NOT NULL
);
