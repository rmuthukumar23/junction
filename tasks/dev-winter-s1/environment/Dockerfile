# The agent's container. It holds tooling only: no scenario, no seed, no engine code.
FROM docker.io/library/node@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS node

FROM docker.io/library/python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates coreutils curl git \
    && rm -rf /var/lib/apt/lists/*
# Node and npm, so the harness can install its agent without an apt round trip.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# Planning and MCP client libraries, available to the agent and used by the oracle.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
WORKDIR /app
