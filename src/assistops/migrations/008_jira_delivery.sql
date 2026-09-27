ALTER TABLE event_jobs DROP CONSTRAINT event_jobs_status_check;
ALTER TABLE event_jobs ADD CONSTRAINT event_jobs_status_check
    CHECK (status IN ('pending', 'processing', 'awaiting_approval', 'awaiting_delivery',
                      'delivery_uncertain', 'completed', 'failed'));

-- Approval and pending delivery commit together, before any external write.
CREATE TABLE ticket_deliveries (
    proposal_id uuid PRIMARY KEY REFERENCES ticket_proposals(id),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'succeeded', 'failed', 'uncertain')),
    attempts integer NOT NULL DEFAULT 0,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    issue_key text,
    error_code text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
