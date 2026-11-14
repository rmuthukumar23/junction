"""Standalone Modal connectivity and parallelism check.

Not wired into envkit or the judge. Uses only CPU containers and costs a few
cents at most. Run from the repo root:

    python -m modal run test/modal_check.py
    python -m modal run test/modal_check.py --n 20 --work-seconds 5
"""

import os
import socket
import time

import modal

app = modal.App("junction-modal-check")
image = modal.Image.debian_slim(python_version="3.12")


@app.function(image=image, timeout=120)
def work(i: int, seconds: float) -> dict:
    """Stand-in for one small environment episode."""
    start = time.time()
    time.sleep(seconds)
    return {
        "i": i,
        "container": os.environ.get("MODAL_TASK_ID", socket.gethostname()),
        "pid": os.getpid(),
        "started": start,
        "ended": time.time(),
    }


@app.local_entrypoint()
def main(n: int = 8, work_seconds: float = 3.0):
    # 1. Sandbox: an isolated container we drive from the outside, which is
    #    what a Harbor-style agent environment would look like.
    t0 = time.time()
    sb = modal.Sandbox.create(app=app, image=image, timeout=120)
    try:
        proc = sb.exec("python", "-c", "import sys;print('sandbox python', sys.version.split()[0])")
        print(proc.stdout.read().strip(), f"({time.time() - t0:.1f}s incl. cold start)")
    finally:
        sb.terminate()

    # 2. Parallel fan-out: n containers at once, each sleeping work_seconds.
    t0 = time.time()
    results = list(work.starmap([(i, work_seconds) for i in range(n)]))
    wall = time.time() - t0
    containers = {r["container"] for r in results}
    first_start = min(r["started"] for r in results)
    last_end = max(r["ended"] for r in results)
    print(f"tasks={n} distinct_containers={len(containers)}")
    print(f"serial would take {n * work_seconds:.1f}s; wall {wall:.1f}s; "
          f"execution span {last_end - first_start:.1f}s")
