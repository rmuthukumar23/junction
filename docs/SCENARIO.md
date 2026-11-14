# Shift Planner contract · shift-v1

## Objective and observations

Maximize `sum(value of jobs completed by deadline) / sum(value of all jobs)`.
The denominator is fixed, positive and includes unfinished jobs. Late jobs and
jobs still running at termination earn zero. Completion exactly at the deadline
counts. On-time work is retained after interruption.

Eight jobs by default; calibration supports ten or twelve with unchanged rules.
Each public job has `id`, positive integer `duration`, `technicians` (one or two),
`equipment` (`lathe`, `bench`, or null), `prerequisites`, `deadline`, `value`.
Instances expose `shift_end`, `technician_capacity=2`, `action_limit=64`, seed and
generator version. Both equipment types have capacity one.

Observations include the complete instance/hash, time, starts, completed/running
jobs, resource occupancy, actions used, terminal flag/reason, and any last error.
No witness or answer schedule is exposed. IDs are shuffled independently of the
construction order. The reference reads the public instance only.

## Tools and exact semantics

Local action objects use `{"tool": "start_job", "job_id": "J01"}` or analogous
keys below. MCP presents four separate named tools; arguments have the same shape
without the `tool` field. The harness alone calls `reset(seed)`.

Over MCP each tool result is JSON `{"ok": true, "result": <observation>, "header": {...}}`
or `{"ok": false, "error": {"code", "message"}, "header": {...}}`. The header
repeats `time`, `shift_end`, `actions_used`, the actions left (`ops_left`) and
`done`. After an error, call `observe` (free) for the unchanged state.

| Tool | Arguments | Result |
|---|---|---|
| observe | none | Full detached observation; no action charged |
| start_job | job_id: string | Start pending job at current time if all prerequisites completed and resources fit |
| advance | to_time: integer | Strictly greater than now, no greater than shift_end; process all completions up to target |
| finish | none | Stop immediately, preserving only completed credit |

A start does not advance time. Starts are irreversible. Half-open resource
intervals `[start,end)` allow a new job at the exact completion time of another.
A late prerequisite still unlocks its children once it completes. Starting work
that will finish after shift end is legal but cannot earn credit.

Invalid action objects (including extra/missing fields, booleans used as integers,
unknown IDs, duplicate starts, unavailable resources and time reversal) return an
error and consume one action. Jobs/resources/time stay unchanged; reaching the
64-action budget terminates even if the final attempt was invalid. Invalid MCP
tool arguments and unknown tool names are rejected by the backend with exact
JSON types (no coercion) and then passed to the same core validation, so they
consume one action. Malformed protocol envelopes and oversized HTTP requests
are rejected by transport; they never grant credit.

Terminate on finish, all jobs completing, shift end, action exhaustion or harness
interruption. No action after termination changes state or reward. There is no
agent-accessible reset, cancellation, score-setting or file-reading endpoint.

## Generation and reference

The generator uses a seed-local PRNG and positive-duration acyclic job graph.
It constructs a feasible resource-constrained witness and chooses deadlines at
or slightly after witness completion. The witness is discarded from public data.
Reproduction stores the public instance as well as seed, version and SHA-256.

CP-SAT uses required intervals, prerequisite inequalities, cumulative technician
capacity, equipment no-overlap and hard deadlines. Because every generated
instance has an all-on-time solution, finding a feasible schedule proves maximum
reward 1.0. Solver parameters: one worker, random seed 0, deterministic time limit
5; OR-Tools 9.15.6755. Execute that schedule through legal actions, then independently
check intervals and replay the trusted record. No construction witness is read.

This reference deliberately refuses to claim optimality for infeasible custom
instances. Scheduling difficulty is not yet established against a frontier model.

## Calibration protocol

Development seeds 0–4; reference feasibility checks 0–99. Seeds 100–102 stay
reserved until the scenario is frozen. First run the event's frontier model at
eight jobs, keeping legitimate code and optimization tools available. Increase
job count only after observed evidence; record changes and rerun the same
development seeds. Freeze version/limits before final held-out evaluation.
