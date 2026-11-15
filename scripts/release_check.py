"""Release check: is main consistent and ready for the judges?

    uv run --no-sync python scripts/release_check.py          # about 3-5 minutes
    uv run --no-sync python scripts/release_check.py --fast   # skip the audit (about 1-2 minutes)

Runs, in order, and prints PASS/FAIL for each:
  1. the quick check (scripts/quick.sh): compile, tests, quick tasks current;
  2. the benchmark tasks match the code (tasks/normal-winter-s*), and the verifier regrades
     a trace with no notes (ENVKIT_TEST_SCENARIO=normal-winter integrity tests);
  3. the reward audit on every committed normal-winter seed;
  4. every scripted grower plays the whole episode without a tool fault, and the viewer
     shows the real game exactly (scripts/viz/check_viewer.py);
  5. the README's results table matches the committed calibration (reference and
     nobody-acts profit on the committed seeds);
  6. the judge path names a committed scenario and the generated tasks exist for each seed.
Exits non-zero if anything fails. It changes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = "normal-winter"


def run(cmd: list[str], env: dict | None = None, timeout: int = 1800) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, **(env or {})})
    out = "\n".join(l for l in (p.stdout + p.stderr).splitlines() if "UV_NATIVE_TLS" not in l)
    return p.returncode, out


def seeds() -> list[int]:
    cal = json.loads((ROOT / "calibration.json").read_text())["tasks"].get(SCENARIO, {})
    return sorted(int(s) for s in cal)


def check_quick() -> tuple[bool, str]:
    code, out = run(["bash", "scripts/quick.sh"])
    return code == 0, out.strip().splitlines()[-1] if out.strip() else ""


def check_tasks() -> tuple[bool, str]:
    code, out = run([sys.executable, "-m", "pytest", "tests/envkit/test_integrity.py", "-q", "-p", "no:cacheprovider",
                     "-k", "not audit"], env={"ENVKIT_TEST_SCENARIO": SCENARIO})
    last = [l for l in out.splitlines() if "passed" in l or "failed" in l]
    fails = [l for l in out.splitlines() if l.startswith("FAILED")]
    return code == 0, (last[-1] if last else out[-300:]) + ("\n    " + "\n    ".join(fails) if fails else "")


def check_audit() -> tuple[bool, str]:
    def one(seed: int) -> tuple[int, bool, str]:
        code, out = run(["uv", "run", "--no-sync", "envkit", "audit", SCENARIO, "--seed", str(seed)])
        bad = [l.strip() for l in out.splitlines() if "[FAIL]" in l]
        return seed, code == 0 and "Audit passed" in out, "; ".join(bad)
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(one, seeds()))
    ok = all(r[1] for r in results)
    return ok, ", ".join(f"seed {s} {'pass' if p else 'FAIL: ' + why}" for s, p, why in results)


def check_viewer() -> tuple[bool, str]:
    code, out = run(["uv", "run", "--no-sync", "python", "scripts/viz/check_viewer.py", "--scenario", SCENARIO])
    bad = [l for l in out.splitlines() if "FAIL" in l or "✗" in l]
    return code == 0, ("all scripted growers: real game, ledger exact" if code == 0 else "\n    ".join(bad[:8]))


def check_readme() -> tuple[bool, str]:
    """The README's Results rows for committed seeds must match calibration.json profits."""
    readme = (ROOT / "README.md").read_text()
    cal = json.loads((ROOT / "calibration.json").read_text())["tasks"].get(SCENARIO, {})
    problems, checked = [], 0
    for seed, entry in cal.items():
        m = re.search(rf"^\| {seed} \(dev\) \|(.+)$", readme, re.M)
        if not m:
            problems.append(f"no README row for seed {seed}")
            continue
        cells = [c.strip() for c in m.group(1).split("|") if c.strip()]
        nums = [float(re.sub(r"[^\d.-]", "", c.split("(")[0].replace("−", "-"))) for c in cells]
        want_ref = entry["anchors"]["reference"]["metrics"]["profit_eur"]
        want_zero = entry["anchors"]["do-nothing"]["metrics"]["profit_eur"]
        if abs(nums[-1] - want_ref) > 1.0:
            problems.append(f"seed {seed}: README reference {nums[-1]:,.0f} vs calibration {want_ref:,.0f}")
        if abs(nums[0] - want_zero) > 1.0:
            problems.append(f"seed {seed}: README nobody {nums[0]:,.0f} vs calibration {want_zero:,.0f}")
        checked += 1
    return not problems, ("; ".join(problems) if problems else f"seeds {sorted(cal)} match calibration.json")


def check_judge_path() -> tuple[bool, str]:
    judge = (ROOT / "scripts" / "judge.sh").read_text()
    default = re.search(r"ENVKIT_SCENARIO:-([\w-]+)", judge)
    scen = default.group(1) if default else "?"
    missing = [s for s in seeds() if not (ROOT / "tasks" / f"{SCENARIO}-s{s}" / "task.toml").exists()]
    ok = scen == SCENARIO and (ROOT / "scenarios" / f"{scen}.toml").exists() and not missing
    return ok, f"judge.sh default scenario {scen}; tasks for seeds {seeds()}" + (f"; missing {missing}" if missing else " present")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the reward audit")
    a = ap.parse_args()
    head = run(["git", "log", "--oneline", "-1"])[1].strip()
    print(f"Release check on {head}\n")
    checks = [("quick check", check_quick), ("benchmark tasks current, verifier clean", check_tasks)]
    if not a.fast:
        checks.append(("reward audit, every committed seed", check_audit))
    checks += [("scripted growers and viewer exact", check_viewer), ("README results match calibration", check_readme),
               ("judge path", check_judge_path)]
    failed = 0
    for name, fn in checks:
        t = time.time()
        try:
            ok, detail = fn()
        except Exception as exc:  # a check that crashes is a failure, not a pass
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ({time.time() - t:.0f} s)\n    {detail}")
    print("\nAll checks passed." if not failed else f"\n{failed} check(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
