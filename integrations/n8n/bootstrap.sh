#!/bin/sh
set -eu
# Never overwrite credentials or workflows edited after the first installation.
if [ ! -f /home/node/.n8n/assistops-initialized ]; then
  n8n import:credentials --input=/opt/assistops/fixtures/credentials.json
  n8n import:workflow --input=/opt/assistops/fixtures/workflow.json
  n8n publish:workflow --id=assistopsWebhookV1
  touch /home/node/.n8n/assistops-initialized
fi
