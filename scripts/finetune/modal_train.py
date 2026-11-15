"""LoRA fine-tuning of Qwen3-4B-Instruct-2507 on the reference planner's decisions, on Modal.

    uv run --no-sync modal run --detach scripts/finetune/modal_train.py
    uv run --no-sync modal run --detach scripts/finetune/modal_train.py --epochs 1 --max-examples 256   # ~30 min

The local entrypoint uploads artifacts/finetune/data/train.jsonl (from gen_data.py) to the
Modal Volume `greenhouse-ft` at /data/train.jsonl, then trains on one H100 and saves the
adapter to /lora/greenhouse-qwen3-4b on the same Volume, where modal_serve.py loads it.
`--detach` keeps the run going if your terminal closes; follow it with
`uv run --no-sync modal app logs greenhouse-ft-train` or at https://modal.com/apps.

Each row is rendered with the model's own chat template (tools included), split into the
prompt (system + user turn) and the completion (the assistant's <tool_call> block), and the
loss is taken on the completion only. The model is run with `logits_to_keep`, so the 150k-
word vocabulary is projected only for the completion tokens, not the ~18k prompt tokens.
Rows longer than --max-length are skipped (truncating would cut the answer off); if more than 5 %
would be skipped, training stops with an error instead. Rows are about 10-13.5k tokens
with the compact prompt (common.system_prompt; compact JSON is about 2.4 characters per token).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import modal

BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
ADAPTER = "/vol/lora/greenhouse-qwen3-4b"
DATA = "/vol/data/train.jsonl"


def local_data() -> Path:
    """artifacts/finetune/data in the repo. Only called on your machine: inside the container
    this file is /root/modal_train.py, which has no repo around it."""
    return Path(__file__).resolve().parents[2] / "artifacts" / "finetune" / "data"

app = modal.App("greenhouse-ft-train")
volume = modal.Volume.from_name("greenhouse-ft", create_if_missing=True)
hf_cache = modal.Volume.from_name("greenhouse-hf-cache", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.8.0",
        "transformers==4.56.2",
        "peft==0.17.1",
        "accelerate==1.10.1",
    )
)


@app.function(image=image, gpu="H100", timeout=4 * 3600,
              volumes={"/vol": volume, "/root/.cache/huggingface": hf_cache})
def train(epochs: float = 2.0, max_examples: int = 0, lr: float = 2e-4, rank: int = 32,
          max_length: int = 16384, grad_accum: int = 4, seed: int = 0, save_every: int = 8,
          resume: bool = False, focus: str = "", focus_share: float = 0.75) -> dict:
    import random

    import torch
    import torch.nn.functional as F
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import (AutoModelForCausalLM, AutoTokenizer, Trainer, TrainerCallback,
                              TrainingArguments)

    started = time.time()
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    rows = [json.loads(line) for line in open(DATA)]
    random.Random(seed + (100 if resume else 0)).shuffle(rows)    # a resumed round draws other rows
    wanted = {t.strip() for t in focus.split(",") if t.strip()}
    if wanted:                      # bias the sample toward mornings that use the focus actions
        def uses(row):
            args = json.loads(row["messages"][-1]["tool_calls"][0]["function"]["arguments"])
            return bool(wanted & {a.get("tool") for a in args.get("actions", [])})
        hit = [r for r in rows if uses(r)]
        rest = [r for r in rows if not uses(r)]
        n = max_examples or len(rows)
        k = min(len(hit), round(n * focus_share))
        rows = hit[:k] + rest[:n - k]
        random.Random(seed + 1).shuffle(rows)
        print(f"focus {sorted(wanted)}: {k} of {len(rows)} examples use them ({len(hit)} available)", flush=True)
    elif max_examples:
        rows = rows[:max_examples]

    examples, skipped, lengths = [], {"too_long": 0, "template": 0}, []
    for row in rows:
        msgs, tools = row["messages"], row.get("tools")
        prompt = tok.apply_chat_template(msgs[:-1], tools=tools, add_generation_prompt=True, tokenize=False)
        full = tok.apply_chat_template(msgs, tools=tools, tokenize=False)
        if not full.startswith(prompt):
            skipped["template"] += 1
            continue
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        c_ids = tok(full[len(prompt):].rstrip("\n"), add_special_tokens=False)["input_ids"]
        if len(p_ids) + len(c_ids) > max_length:
            skipped["too_long"] += 1
            continue
        examples.append({"input_ids": p_ids + c_ids, "n_completion": len(c_ids)})
        lengths.append(len(p_ids) + len(c_ids))
    print(f"{len(examples)} examples, skipped {skipped}, tokens mean {sum(lengths) / max(1, len(lengths)):.0f} "
          f"max {max(lengths, default=0)}, total {sum(lengths):,}", flush=True)
    dropped = skipped["too_long"] + skipped["template"]
    if dropped > 0.05 * len(rows):          # never train quietly on a fraction of the data
        raise RuntimeError(f"{dropped} of {len(rows)} rows skipped ({skipped}); rows are "
                           f"{min(lengths, default=0)}-{max(lengths, default=0)} tokens among those kept. "
                           f"Raise --max-length or shorten the prompt, then rerun.")
    print("example completion:", tok.decode(examples[0]["input_ids"][-examples[0]["n_completion"]:])[:400], flush=True)

    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.bfloat16, attn_implementation="sdpa")
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model.config.use_cache = False
    if resume:                      # continue from the saved adapter; keep a copy of it first
        import shutil
        if not Path(ADAPTER, "adapter_config.json").exists():
            raise RuntimeError(f"--resume: no adapter at {ADAPTER}")
        previous = json.loads(Path(ADAPTER, "train_info.json").read_text()) if Path(ADAPTER, "train_info.json").exists() else {}
        backup = f"{ADAPTER}-round{previous.get('round', 1)}"
        shutil.rmtree(backup, ignore_errors=True)
        shutil.copytree(ADAPTER, backup)
        volume.commit()
        print(f"resuming from {ADAPTER} (copy kept at {backup})", flush=True)
        model = PeftModel.from_pretrained(model, ADAPTER, is_trainable=True)
    else:
        previous = {}
        model = get_peft_model(model, LoraConfig(
            r=rank, lora_alpha=2 * rank, lora_dropout=0.05, task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()

    class Rows(torch.utils.data.Dataset):
        def __len__(self):
            return len(examples)

        def __getitem__(self, i):
            return examples[i]

    def collate(batch):                       # batch size 1: no padding needed
        (b,) = batch
        return {"input_ids": torch.tensor([b["input_ids"]]), "n_completion": torch.tensor(b["n_completion"])}

    class CompletionTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            ids, n = inputs["input_ids"], int(inputs["n_completion"])
            out = model(input_ids=ids, logits_to_keep=n + 1, use_cache=False)
            logits = out.logits[:, :-1, :].float()          # predictions for the last n tokens
            loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), ids[:, -n:].reshape(-1))
            return (loss, out) if return_outputs else loss

    args = TrainingArguments(
        output_dir="/tmp/out", per_device_train_batch_size=1, gradient_accumulation_steps=grad_accum,
        num_train_epochs=epochs, learning_rate=lr, lr_scheduler_type="cosine", warmup_ratio=0.03,
        bf16=True, logging_steps=5, save_strategy="no", report_to=[], remove_unused_columns=False,
        dataloader_num_workers=0, seed=seed, gradient_checkpointing=False,   # enabled on the model above
    )

    class SaveEvery(TrainerCallback):
        """Write the adapter to the Volume every `save_every` steps, so a cancelled run (a stray
        Ctrl+C, a lost connection) still leaves a usable adapter with its step in train_info.json."""

        def on_step_end(self, args, state, control, **kw):
            if save_every and state.global_step % save_every == 0 and state.global_step < state.max_steps:
                save(state.global_step, state.max_steps, partial=True)

    def save(step: int, total: int, partial: bool) -> dict:
        Path(ADAPTER).mkdir(parents=True, exist_ok=True)
        model.save_pretrained(ADAPTER)
        tok.save_pretrained(ADAPTER)
        log = [h for h in trainer.state.log_history if "loss" in h]
        info = {"base_model": BASE_MODEL, "adapter": ADAPTER, "examples": len(examples), "skipped": skipped,
                "tokens": sum(lengths), "epochs": epochs, "lr": lr, "lora_rank": rank, "lora_alpha": 2 * rank,
                "max_length": max_length, "grad_accum": grad_accum, "seed": seed, "step": step, "steps": total,
                "partial": partial, "round": previous.get("round", 1) + 1 if resume else 1,
                "resumed_from": previous.get("examples") if resume else None, "focus": sorted(wanted),
                "first_loss": log[0]["loss"] if log else None,
                "last_loss": log[-1]["loss"] if log else None, "loss_log": log,
                "minutes": round((time.time() - started) / 60, 1)}
        Path(ADAPTER, "train_info.json").write_text(json.dumps(info, indent=1))
        volume.commit()
        print(f"saved adapter at step {step}/{total}{' (partial)' if partial else ''}", flush=True)
        return info

    trainer = CompletionTrainer(model=model, args=args, train_dataset=Rows(), data_collator=collate,
                                callbacks=[SaveEvery()])
    trainer.train()
    info = save(trainer.state.global_step, trainer.state.max_steps, partial=False)

    print(json.dumps({k: v for k, v in info.items() if k != "loss_log"}, indent=1), flush=True)
    return info


@app.local_entrypoint()
def main(epochs: float = 2.0, max_examples: int = 0, lr: float = 2e-4, rank: int = 32,
         max_length: int = 16384, grad_accum: int = 4, save_every: int = 8, resume: bool = False,
         focus: str = "", focus_share: float = 0.75, upload: bool = True):
    local = local_data()
    data = local / "train.jsonl"
    if upload:
        if not data.exists():
            raise SystemExit(f"{data} is missing: run scripts/finetune/gen_data.py first (or pass --no-upload)")
        print(f"uploading {data} ({data.stat().st_size / 1e6:.0f} MB) to volume greenhouse-ft:/data/train.jsonl")
        with volume.batch_upload(force=True) as batch:
            batch.put_file(str(data), "/data/train.jsonl")
            if (local / "manifest.json").exists():
                batch.put_file(str(local / "manifest.json"), "/data/manifest.json")
    info = train.remote(epochs=epochs, max_examples=max_examples, lr=lr, rank=rank,
                        max_length=max_length, grad_accum=grad_accum, save_every=save_every,
                        resume=resume, focus=focus, focus_share=focus_share)
    out = local.parent / "train_info.json"
    out.write_text(json.dumps(info, indent=1) + "\n")
    print(f"done in {info['minutes']} min, loss {info['first_loss']} -> {info['last_loss']}; wrote {out}")
