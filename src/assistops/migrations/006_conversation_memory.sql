-- Keep the exact routing context with its immutable plan for deterministic retries.
ALTER TABLE supervisor_plans ADD COLUMN context jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX inbound_events_conversation ON inbound_events
    (tenant_id, connector_id, source, (payload->>'user_id'),
     (payload->>'conversation_id'), received_at, id);
