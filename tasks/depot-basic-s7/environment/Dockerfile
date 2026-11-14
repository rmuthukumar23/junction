# The agent's container. It holds tooling only: no scenario, no seed, no engine code.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates coreutils curl git \
    && rm -rf /var/lib/apt/lists/*
# Node and npm, so the harness can install its agent without an apt round trip.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# MCP client library, used by the oracle and available to the agent.
RUN pip install --no-cache-dir mcp==2.3.0
WORKDIR /app
