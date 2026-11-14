#!/bin/bash
# Replays the collected trace in a fresh process and writes the reward.
mkdir -p /logs/verifier
cd /tests/bundle
# No reward file is written if the trace is missing or cannot be graded: that is
# an infrastructure failure, not a score of zero.
exec python3 -m envkit.verify --bundle /tests/bundle --trace /var/lib/envkit/trace.jsonl --out /logs/verifier
