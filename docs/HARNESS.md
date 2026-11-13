# AfterQuery harness integration checklist

The pasted brief identifies Harbor running OpenCode via MCP, but does not supply the starter kit, exact tool schema, or scoring skeleton. Whoever claims the harness issue must obtain those materials and record their versions or commit hashes here before implementing the adapter.

1. Run the starter kit unchanged once. Save the exact command and observed output.
2. Map official `reset`/observation/action/termination/scoring semantics to `junction_env.contracts`. Keep the real scenario core independent of MCP and cloud clients.
3. Expose only agent-visible observations and legal actions. Keep hidden state and judge-only scoring inside the process.
4. Confirm invalid actions, timeout, process restart, do-nothing, and stop-early behavior through the official harness.
5. Add one script and one README command that work from a fresh clone. Record required public dependencies and pinned versions. Do not require Modal, Verda, private credentials, or an existing database for judge execution.
6. Run the exact reference and three frontier-agent calls the judges will use. Capture seeds, model/version, prompts, scores, and compact trajectories in `docs/EXPERIMENTS.md`.

Do not report the toy example or local runner as proof of official harness compatibility.
