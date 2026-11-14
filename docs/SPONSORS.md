# Sponsor scope for this MVP

## Modal — implement now, claim only after running

Use Harbor's native Modal backend for real isolated reference/frontier trials.
The workload is CPU simulation and API-driven agent evaluation; GPUs do not help.
One smoke trial, then three concurrent frontier trials. Keep the same task, trusted
service record and separate verifier as Docker. Measure complete batch duration,
startup, failures and rate limits; compare deterministic replay, not stochastic
model responses. Timebox compatibility to 45 minutes and keep Docker as fallback.

Meaningful evidence: working cloud evaluation, reproducible scores, per-trial
artifacts and a clear explanation of the isolation boundary. Merely generating a
Modal command is not evidence of sponsor use. Cloud execution remains unverified.

## Codex — development evidence

Use Codex for issue-scoped implementation, testing and review in isolated
worktrees. Preserve PR diffs, exact verification commands and bugs found/fixed.
Coordinator and all teammates can develop. GitHub coordinates integration; there
is no shared mutable checkout or master machine dispatching everyone's agents.

## Verda — deferred

After a valid frontier gap, consider many rollouts and smaller-model fine-tuning,
with held-out before/after evidence. Do not add a GPU dependency to this scheduling
MVP to qualify for a prize. No Verda services or training are implemented now.

## Entire — deferred

Keep the existing optional guidance/config for later. No Sessions/Graph/Brain setup
is a prerequisite for this MVP. Adopt it only when shared context retrieval works
for teammates and its benefit can be measured. GitHub history, decisions and PR
handoffs remain sufficient for the current build.

Priorities: valid environment → early frontier pilot → measured gap and exploit
resistance → reliable judge path → cloud evidence → optional sponsor extensions.
