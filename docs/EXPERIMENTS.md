# Reproducible experiment log

No frontier-agent or official harness runs have been completed in this scaffold. Add actual runs below; never invent a result.

| Run ID | Date | Code SHA | Harness version | Policy/model + version | Seed set | Exact command | Score summary | Trace/artifact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

For each candidate scenario, record:

- **Objective and fairness:** what information and actions the agent has, and why success is possible.
- **Reference:** legal policy, fixed/held-out seed scores, and reproducible command.
- **Frontier:** model identifier, prompt, number of runs, per-run scores, and concrete failure traces.
- **Integrity:** do-nothing, early-stop, random, invalid-action, and adversarial exploit strategies; scores compared with reference.
- **Changes:** before/after results on the same fixed seeds plus held-out seeds; explain any variance.
- **Limitations:** known failure modes and what has not been tested.

Store large raw traces in ignored `artifacts/` or a versioned external artifact store; commit compact summaries and enough metadata to reproduce them. Never commit API keys or raw private credentials.
