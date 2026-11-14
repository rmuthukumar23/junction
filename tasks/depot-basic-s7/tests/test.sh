#!/bin/bash
# Replays the collected trace in a fresh process and writes the reward.
mkdir -p /logs/verifier
cd /tests/bundle
python3 -m envkit.verify --bundle /tests/bundle --trace /var/lib/envkit/trace.jsonl --out /logs/verifier
if [ ! -s /logs/verifier/reward.txt ]; then
  echo 0 > /logs/verifier/reward.txt
fi
