FROM docker.n8n.io/n8nio/n8n:2.40.7
COPY --chown=node:node nodes /opt/assistops/nodes
COPY --chown=node:node credentials /opt/assistops/credentials
COPY --chown=node:node fixtures /opt/assistops/fixtures
COPY --chown=node:node bootstrap.sh /opt/assistops/bootstrap.sh
ENV N8N_CUSTOM_EXTENSIONS=/opt/assistops
