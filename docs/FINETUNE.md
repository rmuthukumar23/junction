# Training a small model on Greenhouse Bench

Rubric stretch goal: "Train a smaller model using experience from your environment and show
whether it improves." We distil the scripted reference planner into Qwen3-4B-Instruct-2507:

1. **Experience.** The reference plays dev seeds 1-6 through the same `submit_day` turn an agent
   gets; each morning's briefing and its chosen actions become one training row
   (`scripts/finetune/gen_data.py`).
2. **Training.** LoRA on one H100 on Modal (`scripts/finetune/modal_train.py`).
3. **Serving.** vLLM on Modal serves the base model and the adapter behind one OpenAI-compatible
   URL (`scripts/finetune/modal_serve.py`).
4. **Benchmark.** Base and fine-tuned play held-out seeds 101, 104 and 107, never trained on:
   - locally in-process, scored exactly like the verifier (`scripts/finetune/play_llm.py`);
   - once through Harbor + OpenCode (`scripts/finetune/harbor_run.sh`).
5. **Report.** `scripts/finetune/report.py` writes the table into the README.

Nothing under `src/`, `tasks/` or `calibration.json` changes. `src/envkit` is bundled into the
tasks, so editing it would force a benchmark rebuild.

## Before you start (once, about 5 minutes)

```bash
cd ../JUNCTION-finetune        # or: git switch lukas/finetune
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync modal setup                          # log in with your own Modal account (your $100 credit)
uv run --no-sync modal profile current                # the workspace that holds your credit
```

Pick an API key for the model server and store it in two places:
- in `.env` as `VLLM_API_KEY=<value>`;
- as a Modal secret:

```bash
key=$(openssl rand -hex 16)
echo "VLLM_API_KEY=$key" >> .env
uv run --no-sync modal secret create greenhouse-vllm VLLM_API_KEY=$key
```

The Volume `greenhouse-ft` (data and adapter) and two cache volumes are created on first use.

## Step 1: generate the expert data (local CPU)

```bash
uv run --no-sync python scripts/finetune/gen_data.py --variants 3
```

- What it does: plays 18 reference episodes (6 seeds x 3 variants) on up to 8 processes.
- Output: `artifacts/finetune/data/train.jsonl`, plus `manifest.json` with the profit per episode
  and the row and token counts.
- Expected size: about 13k tokens per row. Each row is a compact system prompt (the scenario prompt
  plus the rules that change decisions: market order book, action docs, objective, repairs; about 4k
  tokens), the last 7 days of the planner's own actions and the morning's briefing with a 48 h forecast.
  The crop, facility and hidden-parameter tables are left out: they are the same every season, so
  the student learns them from the examples, and they would double the prompt (and attention cost
  grows with its square).
- Check that every variant was `kept`. A variant is skipped when dropping actions cost it more than
  10 % of the clean run's profit.
- `--variants 1` gives the clean reference only (252 rows, faster to train).

## Step 2: train on Modal (about 30 min, one H100)

```bash
uv run --no-sync modal run --detach scripts/finetune/modal_train.py --epochs 1 --max-examples 256
```

At about 13k tokens a row this is roughly 6 s an example on one H100, so 256 examples (64 steps of
4) take about 25-30 minutes plus a few minutes of start-up. The progress bar shows the estimate
after the first step; scale `--max-examples` to your time.

- The local entrypoint uploads `train.jsonl` to the Volume, then trains.
- Follow progress with `uv run --no-sync modal app logs greenhouse-ft-train`, or on https://modal.com/apps.
- The log first prints the example and token counts and one decoded completion, which should be
  a `<tool_call>` block. After that, loss is printed every 5 steps.
- Output:
  - the adapter at `greenhouse-ft:/lora/greenhouse-qwen3-4b`;
  - `artifacts/finetune/train_info.json` on your machine (only if the terminal stayed attached;
    otherwise fetch it with `uv run --no-sync modal volume get greenhouse-ft /lora/greenhouse-qwen3-4b/train_info.json artifacts/finetune/train_info.json`).
- Short on time? Lower `--max-examples`; more time? Raise it (all rows: about 2 hours).
- Cost at Modal's H100 rate is a few dollars an hour.

## Step 3: serve both models

```bash
uv run --no-sync modal deploy scripts/finetune/modal_serve.py
```

1. Copy the printed URL (`https://<workspace>--greenhouse-vllm-serve.modal.run`), add `/v1`, and
   put it in `.env` as `FT_BASE_URL=...`.
2. Check the server (the first request waits for the cold start, a few minutes the first time):

```bash
set -a; . ./.env; set +a
curl -s -H "Authorization: Bearer $VLLM_API_KEY" "$FT_BASE_URL/models"
```

The list must contain `Qwen/Qwen3-4B-Instruct-2507` and `greenhouse`. If `greenhouse` is
missing, the adapter was not on the Volume when the server started. Check step 2, then
`uv run --no-sync modal app stop greenhouse-vllm` and deploy again.

## Step 4: benchmark locally (about 10-20 min)

```bash
uv run --no-sync python scripts/finetune/play_llm.py --model Qwen/Qwen3-4B-Instruct-2507 --label base
uv run --no-sync python scripts/finetune/play_llm.py --model greenhouse --label finetuned
```

- Both run in parallel terminals if you like.
- Default seeds are 101, 104 and 107, the scenario is `normal-winter`, and temperature is 0.
- The first run on a held-out seed also calibrates it (plays every scripted anchor once, a few
  minutes). The result is cached under `artifacts/finetune/calibration/`.
- Output: one folder per episode with `trace.jsonl` and `transcript.jsonl` (every model answer),
  plus `results.json` with score, profit, malformed days and refused actions.
- `--runs 3` gives three episodes per seed.
- Endpoint failures are reported as infrastructure failures, not scored as the model's.

## Step 5: one run through the official harness (Harbor + OpenCode)

```bash
bash scripts/finetune/harbor_run.sh 101                                   # fine-tuned
FT_MODEL=Qwen/Qwen3-4B-Instruct-2507 bash scripts/finetune/harbor_run.sh 101   # base, optional
```

This builds `artifacts/finetune/tasks/normal-winter-s101`, then runs one OpenCode attempt with
the model at `vllm/greenhouse` (base URL, key and `openai_chat_completions` format passed to
Harbor). It writes `<job>/summary.json` with the verifier's score. On this machine it uses Podman.

The prompt here differs from training: OpenCode's own system prompt, its extra tools, the full task
instruction (with the crop and facility tables the student never saw), and every briefing kept in
context rather than compacted. Expect it to do worse than the local loop. That
gap is worth reporting too.

If Harbor rejects the model string, add `--skip-model-parsing-and-provider-mapping` (extra
arguments are passed to `harbor run`):

```bash
bash scripts/finetune/harbor_run.sh 101 --skip-model-parsing-and-provider-mapping
```

## Step 6: write the README and open a PR

```bash
uv run --no-sync python scripts/finetune/report.py --print    # look first
uv run --no-sync python scripts/finetune/report.py            # writes between the finetune markers
bash scripts/quick.sh
git add README.md && git commit -m "Fine-tuning results: Qwen3-4B base vs LoRA on held-out seeds"
```

Read the README text above the markers before committing, and adjust the one-line claim to
what the numbers show.

## Step 7: stop paying

```bash
uv run --no-sync modal app stop greenhouse-vllm
```

The server scales to zero after 20 idle minutes anyway. Training stops by itself.

## Optional: share the adapter

The adapter is about 130 MB at rank 32, larger than GitHub allows per file:

```bash
uv run --no-sync modal volume get greenhouse-ft /lora/greenhouse-qwen3-4b artifacts/finetune/adapter
```

Upload it to IronShard or Hugging Face and link it from the README.

## What was run (2026-11-15)

- **Round 1:** 192 examples from the base model, 16 min:
  `modal_train.py --epochs 1 --max-examples 192`.
- **Round 2:** continued from round 1 on 256 examples, 75 % of them mornings that order seed or plant,
  21 min: `modal_train.py --resume --focus plant,place_orders --epochs 1 --max-examples 256 --lr 1e-4`.
  - `--resume` copies the previous adapter to `/lora/greenhouse-qwen3-4b-round1` before training.
  - The Volume's `/lora/greenhouse-qwen3-4b` is now round 2.
  - To serve round 1 again, copy the backup back over it and redeploy.
- **Benchmarks:** labels `base`, `finetuned` (round 1) and `finetuned-r2` (round 2) on seeds 101, 104 and 107.
- **Committed copies** are in `runs/finetune/`: `results.json`, and each episode's trace, transcript and
  result, plus both rounds' `train_info` and the data manifest.
  - `report.py --labels base,finetuned,finetuned-r2` rebuilds the README table from them.
- **The Harbor check was not run** for the fine-tuned model.

## Saving and replaying the runs

The project already records every model run so it can be replayed later.

**How recording works.**
- Every `submit_day` call goes into an append-only `trace.jsonl`:
  - a header with the scenario, seed and code bundle;
  - then, per call, the arguments, the response and a digest of the response.
- The world is deterministic for a seed. Sending the same calls to a fresh simulator therefore
  rebuilds the whole episode hour by hour, and the digests prove that nothing differs.
- This is how the verifier grades: it replays the trace, it does not trust the run.

**Where runs are kept.**

| What | Where | Committed |
|---|---|---|
| Harbor trials (`scripts/judge.sh`, `envkit eval`) | `artifacts/**/var/lib/envkit/trace.jsonl`, with the verifier's `score.json` and OpenCode's `agent/trajectory.json` | No (`artifacts/` is git-ignored) |
| Collected model runs | `runs/normal-winter/<model>-s<seed>-<id>/`: `trace.jsonl`, `score.json`, `trajectory.json`, `meta.json`, `DAYS.md` (`scripts/collect_runs.py`, then `scripts/trajectories.py`) | Yes, 17 runs |

**How they are replayed.**

| Command | What it does |
|---|---|
| `uv run --no-sync envkit replay normal-winter <trace>` | Regrades one trace and reports whether the replay was consistent |
| `uv run --no-sync python scripts/analyze_runs.py` | Replays every committed run hour by hour into `runs/ANALYSIS.md` |
| `uv run --no-sync python scripts/viz/server.py`, then http://localhost:8765 | The viewer: replays committed runs and Harbor traces under `artifacts/` next to the scripted growers |

**The fine-tuning runs fit as follows.**
- **`play_llm.py`** writes the same trace format to `artifacts/finetune/eval/<label>/s<seed>-r<run>/trace.jsonl`.
  - Next to it is `transcript.jsonl`, which holds each day's raw model message, the parsed
    actions, and whether the output was malformed or cut to the action limit.
  - To regrade one: `uv run --no-sync envkit replay normal-winter artifacts/finetune/eval/finetuned/s101-r1/trace.jsonl --seed 101`.
    A held-out seed is calibrated on the fly, which takes a few minutes.
  - The viewer does not list these traces. It only looks for Harbor's `var/lib/envkit/trace.jsonl` layout.
- **`harbor_run.sh`** trials do use Harbor's layout, under `artifacts/finetune/harbor/<job>/<trial>/`.
  The viewer lists them, as "recorded" because the job name does not end in `agent`.
- **Do not copy held-out runs into `runs/normal-winter/`.** `scripts/analyze_runs.py` reads its
  scoring constants from `calibration.json`, which holds only seeds 1-3. It also needs every
  model name in its `NAMES` table, so it would fail on these runs.
- To keep the fine-tuning runs as evidence, commit them under their own folder, for example
  `runs/finetune/<label>/`:
  - `results.json`, plus each episode's `trace.jsonl` and `transcript.jsonl`;
  - each trace is a few hundred KB.

## How to read the result

- The base model has never seen this game's `submit_day` format. Much of any gain may be format
  and habit (valid actions, ordering seed on time, repairing storm damage), not market planning.
  The table shows malformed days and refused actions so that this is visible.
- The student copies a policy that scores 0.80 by construction. Matching it on unseen seeds is
  the ceiling of this method; beating it would need learning from reward (rejection sampling or
  RL), which this does not do.
- The local loop is not the Harbor/OpenCode harness. Report the two separately.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `modal run` image build fails on a pinned package | Change the version pin in `modal_train.py` or `modal_serve.py` to one pip offers and rerun |
| Training runs out of GPU memory | `--max-length 20480` (longer rows are skipped), or `--rank 16` |
| Training stops with `rows skipped ... Raise --max-length` | Rows are longer than the limit (default 16384 tokens; rows are about 10-13.5k). Raise `--max-length`, or lower `HISTORY_DAYS` in `common.py` and regenerate the data |
| vLLM fails on `--max-model-len 131072` | Lower `MAX_MODEL_LEN` in `modal_serve.py` to 65536 and redeploy |
| `play_llm.py` reports every day as malformed for the fine-tuned model | Look at `transcript.jsonl`. Plain-text `<tool_call>` blocks are parsed anyway; if the output is empty, check the server log (`modal app logs greenhouse-vllm`) |
| HTTP 401 | `VLLM_API_KEY` in `.env` differs from the Modal secret; recreate the secret with `--force` and redeploy |
