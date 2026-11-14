# Shift Planner

Complete as much workshop job value as possible before each deadline. Call
observe first to see all jobs and rules. All data is public; no discoveries are
required. There are two technicians, one lathe and one bench.

Use MCP tools observe(), start_job(job_id), advance(to_time), finish().
Starting consumes no virtual time, so you can start independent jobs together.
All prerequisites must have completed before a job starts. Resources are held
until completion. Jobs cannot be cancelled. advance must move strictly forward
and no further than shift_end; it processes all intervening completions.

You have 64 mutating actions, including invalid requests. observe is free.
Invalid requests leave jobs and time unchanged and return a clear error.
Termination occurs at finish, shift end, all jobs completed, action exhaustion,
or harness interruption. Running, late and unstarted jobs receive no credit.
Completion exactly at a deadline counts. Reward is the sum of on-time completed
job values divided by the fixed sum of ALL job values.

You may use Python, OR-Tools, or other code to plan; OR-Tools is installed.
No local output file affects the score. Only actual actions on the environment
count. Finish after completing the work. Do not attempt to reset the episode.

## Interface

Every action goes through the tools of the MCP server `shift-planner` (`http://sim:8000/mcp`), which is already connected. Nothing in this container's filesystem affects your result.

- Every result is JSON with `ok`, then `result` or `error`, then a `header` with the operations left (`ops_left`) and status. When `header.done` is true the episode is over.
- There is no reset and no second attempt. Your result is computed from the state of the world when the episode ends.
