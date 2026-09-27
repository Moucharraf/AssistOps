ALTER TABLE event_jobs
    ADD COLUMN attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    ADD COLUMN next_run_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN lease_token uuid,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN result jsonb,
    ADD COLUMN last_error text,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX event_jobs_due ON event_jobs(next_run_at) WHERE status = 'pending';
CREATE INDEX event_jobs_expired ON event_jobs(lease_expires_at) WHERE status = 'processing';
ALTER TABLE event_audit ADD COLUMN details jsonb NOT NULL DEFAULT '{}'::jsonb;
