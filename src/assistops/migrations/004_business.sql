ALTER TABLE event_jobs DROP CONSTRAINT event_jobs_status_check;
ALTER TABLE event_jobs ADD CONSTRAINT event_jobs_status_check
    CHECK (status IN ('pending', 'processing', 'awaiting_approval', 'completed', 'failed'));

CREATE TABLE ticket_proposals (
    id uuid PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE REFERENCES inbound_events(id),
    arguments jsonb NOT NULL,
    arguments_hash text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    expires_at timestamptz NOT NULL,
    decided_by text,
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Only the synthetic adapter writes here. Real providers need their own idempotency contract.
CREATE TABLE synthetic_tickets (
    id uuid PRIMARY KEY,
    proposal_id uuid NOT NULL UNIQUE REFERENCES ticket_proposals(id),
    tenant_id text NOT NULL,
    customer_id text NOT NULL,
    invoice_id text NOT NULL,
    subject text NOT NULL,
    description text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
