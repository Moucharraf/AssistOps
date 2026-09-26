FROM docker.io/n8nio/n8n:2.40.7@sha256:ffeb52485f78b1b06c9a832205853cf75da72a07a514c9a27724df85979d6c34
COPY --chown=node:node nodes /opt/assistops/nodes
COPY --chown=node:node credentials /opt/assistops/credentials
COPY --chown=node:node fixtures /opt/assistops/fixtures
COPY --chown=node:node bootstrap.sh /opt/assistops/bootstrap.sh
ENV N8N_CUSTOM_EXTENSIONS=/opt/assistops
