"""An OpenAI-compatible vLLM server on Modal serving the base model and the fine-tuned LoRA.

    uv run --no-sync modal deploy scripts/finetune/modal_serve.py
    uv run --no-sync modal app stop greenhouse-vllm          # when done (it also scales to zero when idle)

One URL, two model names:
  Qwen/Qwen3-4B-Instruct-2507   the base model
  greenhouse                    base + the adapter from modal_train.py (Volume greenhouse-ft)

The deploy prints the URL (https://<workspace>--greenhouse-vllm-serve.modal.run). Add /v1 and
put it in .env as FT_BASE_URL. Requests need `Authorization: Bearer $VLLM_API_KEY`; the key
comes from the Modal secret `greenhouse-vllm`:
  uv run --no-sync modal secret create greenhouse-vllm VLLM_API_KEY=<same value as in .env>

Tool calls are parsed with vLLM's hermes parser (Qwen's <tool_call> format). The context is
128k tokens so OpenCode, which keeps every briefing, can play through Harbor; the local
benchmark needs about 20k. The first request after a deploy or an idle period waits for a cold
start (model download on the first ever start, then about 1-3 minutes).
"""
from __future__ import annotations

import os
import subprocess

import modal

BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
ADAPTER = "/vol/lora/greenhouse-qwen3-4b"
MAX_MODEL_LEN = 131072

app = modal.App("greenhouse-vllm")
volume = modal.Volume.from_name("greenhouse-ft", create_if_missing=True)
hf_cache = modal.Volume.from_name("greenhouse-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("greenhouse-vllm-cache", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    # vllm 0.10.2 leaves transformers unpinned; newer transformers dropped
    # `all_special_tokens_extended`, which vllm 0.10.2 calls when it loads the tokenizer.
    .pip_install("vllm==0.10.2", "transformers==4.56.2")
)


@app.function(image=image, gpu="H100", scaledown_window=20 * 60, timeout=24 * 3600,
              volumes={"/vol": volume, "/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
              secrets=[modal.Secret.from_name("greenhouse-vllm")])
@modal.concurrent(max_inputs=32)
@modal.web_server(port=8000, startup_timeout=20 * 60)
def serve():
    volume.reload()
    cmd = ["vllm", "serve", BASE_MODEL, "--host", "0.0.0.0", "--port", "8000",
           "--max-model-len", str(MAX_MODEL_LEN), "--gpu-memory-utilization", "0.90",
           "--enable-auto-tool-choice", "--tool-call-parser", "hermes",
           "--api-key", os.environ["VLLM_API_KEY"]]
    if os.path.exists(os.path.join(ADAPTER, "adapter_config.json")):
        cmd += ["--enable-lora", "--max-lora-rank", "64", "--max-loras", "1",
                "--lora-modules", f"greenhouse={ADAPTER}"]
    else:
        print(f"no adapter at {ADAPTER}: serving the base model only")
    print(" ".join(c if c != os.environ["VLLM_API_KEY"] else "***" for c in cmd), flush=True)
    subprocess.Popen(cmd)
