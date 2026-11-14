"""Replay trusted records, then independently check interval/resource accounting.

Replay does not authenticate the source: use records collected from the trusted
sidecar, never a file submitted by the agent. Missing/invalid evidence is an
infrastructure error, never a zero-score agent result.
"""
from .environment import ShiftPlanner
from .types import EQUIPMENT, Instance


class VerificationError(ValueError):
    pass


def verify_record(record: dict, expected: Instance) -> float:
    try:
        return _verify(record, expected)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise VerificationError(str(exc)) from exc


def _verify(record: dict, expected: Instance) -> float:
    if record["schema_version"] != 1 or record["instance"] != expected.public() or record["instance_hash"] != expected.digest:
        raise VerificationError("instance/schema mismatch")
    history = record["history"]
    if not isinstance(history, list) or len(history) > expected.action_limit:
        raise VerificationError("invalid history length")
    replay = ShiftPlanner(expected)
    for entry in history:
        if replay.done:
            raise VerificationError("history continues after termination")
        result = replay.step(entry["action"])
        if result.observation.get("error") != entry["error"] or replay.time != entry["time"]:
            raise VerificationError("action outcome mismatch")
    final = record["final"]
    if not replay.done and final["done"]:
        reason = final["termination"]
        if reason not in ("policy_stop", "policy_timeout", "policy_error", "step_limit", "harness_interruption"):
            raise VerificationError("invalid external termination")
        replay.interrupt(reason)
    if replay.observe() != final or replay.record()["history"] != history:
        raise VerificationError("replay differs from trusted final state")
    score = check_intervals(expected, final["starts"], final["time"])
    if score != replay.score() or record["score"] != score:
        raise VerificationError("reward accounting mismatch")
    return score


def check_intervals(instance: Instance, starts: dict[str, int], final_time: int) -> float:
    jobs = {j.id: j for j in instance.jobs}
    if type(final_time) is not int or not 0 <= final_time <= instance.shift_end:
        raise VerificationError("invalid final time")
    if not set(starts) <= jobs.keys():
        raise VerificationError("unknown started job")
    ends = {}
    for key, start in starts.items():
        if type(start) is not int or not 0 <= start <= final_time:
            raise VerificationError("invalid start time")
        ends[key] = start + jobs[key].duration
    for key, start in starts.items():
        if any(dep not in ends or ends[dep] > start for dep in jobs[key].prerequisites):
            raise VerificationError("prerequisite violated")
    # Half-open intervals: completion at t frees resources for a start at t.
    for time in sorted(set(starts.values())):
        active = [jobs[k] for k in starts if starts[k] <= time < ends[k]]
        if sum(j.technicians for j in active) > instance.technician_capacity:
            raise VerificationError("technician capacity violated")
        if any(sum(j.equipment == equipment for j in active) > 1 for equipment in EQUIPMENT):
            raise VerificationError("equipment capacity violated")
    return sum(jobs[k].value for k, end in ends.items()
               if end <= final_time and end <= jobs[k].deadline) / sum(j.value for j in instance.jobs)
