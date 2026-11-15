# Agent trajectories

Each run's full Harbor trajectory is `trajectory.json` in its folder; `DAYS.md` is the readable
day-by-day version (what the agent said, what it did, what was refused, cash after the day).

## Current rules (`runs/normal-winter/`)

| Run | Verifier reward | Days | Actions | Refused | Day-by-day |
|---|---:|---:|---:|---:|---|
| claude-haiku-5-5-s1-b7cklh5 | 0.6581 | 42 | 45 | 1 | [DAYS.md](normal-winter/claude-haiku-5-5-s1-b7cklh5/DAYS.md) |
| claude-haiku-5-5-s2-sugfugl | 0.6744 | 42 | 43 | 1 | [DAYS.md](normal-winter/claude-haiku-5-5-s2-sugfugl/DAYS.md) |
| claude-haiku-5-5-s3-vmzikdh | 0.5415 | 42 | 51 | 1 | [DAYS.md](normal-winter/claude-haiku-5-5-s3-vmzikdh/DAYS.md) |
| claude-sonnet-5-5-s1-qxhrmeh | 1.0 ¹ | 42 | 69 | 1 | [DAYS.md](normal-winter/claude-sonnet-5-5-s1-qxhrmeh/DAYS.md) |
| claude-sonnet-5-5-s2-ny8magu | 0.1779 | 9 | 26 | 0 | [DAYS.md](normal-winter/claude-sonnet-5-5-s2-ny8magu/DAYS.md) |
| gemini-4-hydrogen-s1-hiup4hw | 0.9905 ¹ | 42 | 96 | 3 | [DAYS.md](normal-winter/gemini-4-hydrogen-s1-hiup4hw/DAYS.md) |
| gemini-4-hydrogen-s1-plk3gpu | 0.7248 | 42 | 133 | 3 | [DAYS.md](normal-winter/gemini-4-hydrogen-s1-plk3gpu/DAYS.md) |
| gemini-4-hydrogen-s3-bqi5any | 0.7592 | 42 | 106 | 3 | [DAYS.md](normal-winter/gemini-4-hydrogen-s3-bqi5any/DAYS.md) |

¹ Played on the current rules before the reference planner was improved; the verifier's reward is
against the earlier reference. [ANALYSIS.md](ANALYSIS.md) rescores every run against the current one.

## Archived: `no-demand-limit` (earlier rules; scores are on those rules)

| Run | Verifier reward | Days | Actions | Refused | Day-by-day |
|---|---:|---:|---:|---:|---|
| claude-haiku-5-5-s1-eqm8oga | 0.5225 | – | – | – | – |
| claude-haiku-5-5-s1-liuvkuq | 0.4042 | – | – | – | – |
| claude-haiku-5-5-s1-zrajfzu | 0.6282 | – | – | – | – |
| claude-haiku-5-5-s2-bwimwi8 | 0.8074 | – | – | – | – |
| claude-haiku-5-5-s3-ebv73qc | 0.5992 | – | – | – | – |
| claude-sonnet-5-5-s1-fdfdefr | 1.0 | – | – | – | – |
| gemini-4-hydrogen-s1-dchxsnk | 1.0 | – | – | – | – |
| gemini-4-hydrogen-s1-junq9de | 0.2157 | – | – | – | – |
| gemini-4-hydrogen-s1-x5vgn2v | 0.92 | – | – | – | – |

## Archived: `order-key-bug` (earlier rules; scores are on those rules)

| Run | Verifier reward | Days | Actions | Refused | Day-by-day |
|---|---:|---:|---:|---:|---|
| gemini-4-hydrogen-s1-cmzfegp | 0.2498 | – | – | – | [DAYS.md](archive/order-key-bug/gemini-4-hydrogen-s1-cmzfegp/DAYS.md) |
| gemini-4-hydrogen-s1-fgkwrkv | 0.6826 | – | – | – | [DAYS.md](archive/order-key-bug/gemini-4-hydrogen-s1-fgkwrkv/DAYS.md) |
| gemini-4-hydrogen-s1-wvedy92 | 0.2892 | – | – | – | [DAYS.md](archive/order-key-bug/gemini-4-hydrogen-s1-wvedy92/DAYS.md) |

## Archived: `schedule-3day-seed` (earlier rules; scores are on those rules)

| Run | Verifier reward | Days | Actions | Refused | Day-by-day |
|---|---:|---:|---:|---:|---|
| claude-haiku-5-5-s1-o35schd | 0.4563 | 42 | 72 | 1 | [DAYS.md](archive/schedule-3day-seed/claude-haiku-5-5-s1-o35schd/DAYS.md) |
| claude-haiku-5-5-s1-oumizcb | 0.4932 | 42 | 69 | 2 | [DAYS.md](archive/schedule-3day-seed/claude-haiku-5-5-s1-oumizcb/DAYS.md) |
| claude-haiku-5-5-s1-xbg69r2 | 0.7193 | 42 | 86 | 1 | [DAYS.md](archive/schedule-3day-seed/claude-haiku-5-5-s1-xbg69r2/DAYS.md) |
| claude-haiku-5-5-s2-gmvk7by | 0.5608 | 42 | 63 | 1 | [DAYS.md](archive/schedule-3day-seed/claude-haiku-5-5-s2-gmvk7by/DAYS.md) |
| claude-haiku-5-5-s3-yd9udcx | 0.4872 | 42 | 65 | 2 | [DAYS.md](archive/schedule-3day-seed/claude-haiku-5-5-s3-yd9udcx/DAYS.md) |
| claude-sonnet-5-5-s1-mavj5wf | 0.818 | 42 | 53 | 1 | [DAYS.md](archive/schedule-3day-seed/claude-sonnet-5-5-s1-mavj5wf/DAYS.md) |
| claude-sonnet-5-5-s1-qzppyvk | 0.7456 | 42 | 59 | 2 | [DAYS.md](archive/schedule-3day-seed/claude-sonnet-5-5-s1-qzppyvk/DAYS.md) |
| claude-sonnet-5-5-s1-tgg9n9g | 0.708 | 42 | 53 | 1 | [DAYS.md](archive/schedule-3day-seed/claude-sonnet-5-5-s1-tgg9n9g/DAYS.md) |
| claude-sonnet-5-5-s2-gwpchtv | 0.809 | 42 | 67 | 1 | [DAYS.md](archive/schedule-3day-seed/claude-sonnet-5-5-s2-gwpchtv/DAYS.md) |
| claude-sonnet-5-5-s3-gc7opsk | 0.7999 | 42 | 72 | 4 | [DAYS.md](archive/schedule-3day-seed/claude-sonnet-5-5-s3-gc7opsk/DAYS.md) |
| gemini-4-hydrogen-s1-wdhrxqr | 0.8177 | 42 | 107 | 2 | [DAYS.md](archive/schedule-3day-seed/gemini-4-hydrogen-s1-wdhrxqr/DAYS.md) |
| gemini-4-hydrogen-s1-xdcsfea | 0.7462 | 42 | 119 | 4 | [DAYS.md](archive/schedule-3day-seed/gemini-4-hydrogen-s1-xdcsfea/DAYS.md) |
| gemini-4-hydrogen-s1-xo7zska | 0.7776 | 42 | 128 | 2 | [DAYS.md](archive/schedule-3day-seed/gemini-4-hydrogen-s1-xo7zska/DAYS.md) |
| gemini-4-hydrogen-s2-rbheld4 | 0.8081 | 42 | 98 | 4 | [DAYS.md](archive/schedule-3day-seed/gemini-4-hydrogen-s2-rbheld4/DAYS.md) |
| gemini-4-hydrogen-s3-e53yzfh | 0.8028 | 42 | 116 | 2 | [DAYS.md](archive/schedule-3day-seed/gemini-4-hydrogen-s3-e53yzfh/DAYS.md) |

## Archived: `steady-demand` (earlier rules; scores are on those rules)

| Run | Verifier reward | Days | Actions | Refused | Day-by-day |
|---|---:|---:|---:|---:|---|
| claude-haiku-5-5-s1-bwxk722 | 0.5615 | – | – | – | [DAYS.md](archive/steady-demand/claude-haiku-5-5-s1-bwxk722/DAYS.md) |
| claude-haiku-5-5-s1-sn3bnta | 0.6729 | – | – | – | [DAYS.md](archive/steady-demand/claude-haiku-5-5-s1-sn3bnta/DAYS.md) |
| claude-haiku-5-5-s1-y54zlbo | 0.7445 | – | – | – | [DAYS.md](archive/steady-demand/claude-haiku-5-5-s1-y54zlbo/DAYS.md) |
| claude-haiku-5-5-s2-chhetag | 0.6966 | – | – | – | – |
| claude-haiku-5-5-s3-w63evtk | 0.8295 | – | – | – | – |
| claude-sonnet-5-5-s1-26hv7nt | 0.7367 | – | – | – | – |
| claude-sonnet-5-5-s1-aahi6f9 | 0.7217 | – | – | – | – |
| claude-sonnet-5-5-s1-rtqkk4e | 0.75 | – | – | – | – |
| gemini-4-hydrogen-s1-9okhwsq | 0.7092 | – | – | – | – |
| gemini-4-hydrogen-s1-ny7vhjc | 0.7721 | – | – | – | – |
| gemini-4-hydrogen-s1-ybj2kwk | 0.8285 | – | – | – | – |
| gemini-4-hydrogen-s2-c6qbm67 | 0.7285 | – | – | – | – |
| gemini-4-hydrogen-s3-akzsgnb | 0.627 | – | – | – | – |
