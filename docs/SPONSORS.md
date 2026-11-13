# Sponsor integration gates

Build one convincing AfterQuery environment first. Each sponsor component must perform a real function and have measured evidence.

| Sponsor | Meaningful use | Gate before spending time | Evidence to show |
| --- | --- | --- | --- |
| Codex | Build/review scoped implementation PRs and help integrate failing checks | Working issue and isolated branch | PRs, diffs, review findings, tests fixed |
| Entire | Sessions for handoff; Graph for code navigation; Brain for reviewed decisions; Trails for review if compatible with GitHub flow | Teammate can retrieve a checkpoint and decision | Checkpoint links, graph query, Brain retrieval, Trail review |
| Modal | Fan out real evaluation episodes or sandbox agent code; optionally serve a public demo endpoint | Local deterministic episode and official harness path work | Same-seed scores, speedup, public URL if deployed |
| Verda | Large-scale rollouts and GPU fine-tuning of a smaller policy; use batch/instance service suited to the actual workload | Valid gap, stored trajectories, training plan, available credits | Baseline vs fine-tuned held-out scores, compute used, reproducible recipe |

Cloud work is an optional accelerator and demo layer. The submitted environment, reference policy, reward tests, and judge command must still work locally. If time is short, finish the AfterQuery acceptance gates before starting Verda training. Document Verda process and share the required summary link in its Discord channel only after the experiment is real.
