"""The fine-tuning scripts (scripts/finetune/) on the 1-day smoke scenario only: no benchmark
episode, no model, no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "finetune"))

import common  # noqa: E402
import gen_data  # noqa: E402
import play_llm  # noqa: E402
import report  # noqa: E402

from envkit.core import replay  # noqa: E402
from envkit.trace import read_trace  # noqa: E402


def test_instruction_matches_the_committed_task():
    scenario = common.scenario_from("smoke")
    assert common.instruction(scenario, 1) == (ROOT / "tasks" / "smoke-s1" / "instruction.md").read_text()


def test_compact_prompt_keeps_the_market_and_drops_the_static_tables():
    scenario = common.scenario_from("smoke")
    full, compact = common.instruction(scenario, 1), common.system_prompt(scenario, 1)
    assert len(compact) < len(full) / 2
    assert '"business"' in compact and '"turn"' in compact and '"crops"' not in compact
    briefing = {"status": {}, "forecast": {"weather": {"hour": list(range(72))}, "note": "x"}}
    trimmed = common.trim_briefing(briefing)
    assert trimmed["forecast"]["weather"]["hour"] == list(range(common.FORECAST_HOURS))
    assert briefing["forecast"]["weather"]["hour"] == list(range(72))           # the original is untouched


def test_held_out_seeds_are_refused_for_training(tmp_path):
    with pytest.raises(SystemExit):
        gen_data.main(["--scenario", "smoke", "--seeds", "1,101", "--out", str(tmp_path)])


def test_gen_data_writes_one_tool_call_per_morning(tmp_path):
    assert gen_data.main(["--scenario", "smoke", "--seeds", "1", "--variants", "2", "--drop-prob", "1",
                          "--workers", "1", "--out", str(tmp_path)]) == 0
    rows = [json.loads(line) for line in (tmp_path / "train.jsonl").read_text().splitlines()]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(rows) == manifest["rows"] == 2
    for row in rows:
        system, user, assistant = row["messages"]
        assert system["role"] == "system" and "## Rules (abridged)" in system["content"]
        assert "This morning's briefing" in user["content"]
        (call,) = assistant["tool_calls"]
        assert call["function"]["name"] == common.TOOL
        actions, malformed = common.parse_actions(assistant)
        assert actions and not malformed
        assert [t["function"]["name"] for t in row["tools"]] == [common.TOOL]
    assert rows[0]["messages"][-1] == rows[1]["messages"][-1]      # the label is the full choice, even if dropped
    assert manifest["episodes"][1]["dropped"] == 1


def test_history_entry_reads_refused_actions_and_calls():
    refused = {"ok": True, "result": {"results": [
        {"tool": "plant", "ok": False, "error": "no seedlings in stock"}, {"tool": "harvest", "ok": True}]}}
    assert common.history_entry(3, [{"tool": "plant"}], refused)["refused"] == [
        {"tool": "plant", "error": "no seedlings in stock"}]
    call = {"ok": False, "error": {"code": "invalid_arguments", "message": "too many actions"}}
    assert common.history_entry(3, [], call)["call_refused"] == "too many actions"


def test_play_llm_counts_a_refused_action(tmp_path):
    bad_plant = {"tool_calls": [{"function": {"name": "env_submit_day", "arguments": json.dumps(
        {"actions": [{"tool": "harvest", "batch_ids": ["ZZ9"]}]})}}]}     # unknown batch: refused, a string error
    result = play_llm.play_episode("smoke", 1, 1, str(tmp_path), chat=lambda m, t: bad_plant)
    assert result["refused_actions"] >= 1 and result["malformed_days"] == 0


def test_parse_actions():
    ok = {"tool_calls": [{"function": {"name": "env_submit_day", "arguments": '{"actions":[{"tool":"harvest"}]}'}}]}
    assert common.parse_actions(ok) == ([{"tool": "harvest"}], False)
    text = {"content": '<tool_call>\n{"name": "env_submit_day", "arguments": {"actions": []}}\n</tool_call>'}
    assert common.parse_actions(text) == ([], False)
    assert common.parse_actions({"content": "heat it up"}) == ([], True)
    assert common.parse_actions({"tool_calls": [{"function": {"name": "env_submit_day", "arguments": "{bad"}}]}) == ([], True)
    assert common.parse_actions({"content": '{"actions": [{"tool": "plant"}, 3]}'}) == ([{"tool": "plant"}], True)
    assert common.parse_actions(None) == ([], True)


def _reference_message(tmp_path: Path) -> dict:
    gen_data.main(["--scenario", "smoke", "--seeds", "1", "--variants", "1", "--workers", "1", "--out", str(tmp_path)])
    return json.loads((tmp_path / "train.jsonl").read_text().splitlines()[0])["messages"][-1]


def test_play_llm_replaying_the_reference_earns_its_profit(tmp_path):
    message = _reference_message(tmp_path / "data")
    scenario = common.scenario_from("smoke")
    reference = gen_data.play("smoke", 1, 0, 0.0)["profit_eur"]
    result = play_llm.play_episode("smoke", 1, 1, str(tmp_path / "eval"), chat=lambda m, t: message)
    assert result["profit_eur"] == pytest.approx(reference)
    assert result["malformed_days"] == 0 and result["infrastructure_failure"] is None
    records = read_trace(tmp_path / "eval" / "s1-r1" / "trace.jsonl")
    episode, mismatches = replay(scenario, 1, records)
    assert not mismatches
    assert episode.result()["profit_eur"] == pytest.approx(reference)


def test_play_llm_survives_garbage_and_infra_failure(tmp_path):
    bad = play_llm.play_episode("smoke", 1, 1, str(tmp_path), chat=lambda m, t: {"content": "no idea"})
    assert bad["malformed_days"] == bad["days"] >= 1 and bad["reward"] is not None

    def down(messages, tools):
        raise play_llm.InfraError("endpoint unreachable")
    infra = play_llm.play_episode("smoke", 1, 2, str(tmp_path), chat=down)
    assert infra["infrastructure_failure"] and infra["reward"] is None


def test_report_replaces_only_the_marked_block(tmp_path):
    root = tmp_path / "ft"
    (root / "eval" / "base").mkdir(parents=True)
    episode = {"seed": 101, "run": 1, "reward": 0.1, "profit_eur": 90000.0, "malformed_days": 3, "days": 42,
               "refused_actions": 4, "seed_stockouts": 1, "truncated_days": 0, "infrastructure_failure": None,
               "reference_profit_eur": 834036.0}
    (root / "eval" / "base" / "results.json").write_text(json.dumps({
        "label": "base", "model": "Qwen/Qwen3-4B-Instruct-2507", "scenario": "normal-winter", "episodes": [episode],
        "command": "play_llm.py --label base", "code_sha": "abcdef1234567", "created": "now",
        "settings": {"temperature": 0.0, "tool_choice": "auto"}, "infrastructure_failures": 0}))
    new = report.block(["base", "finetuned"], root, runs=tmp_path / "no-runs")
    assert "| 101 | 834 k | 0.10 (90 k) | 42, 3 malformed |" in new
    text = f"intro\n{report.START}\nold\n{report.END}\noutro\n"
    out = report.replace_block(text, new)
    assert out.startswith("intro\n") and out.endswith("\noutro\n") and "old" not in out
    assert report.START in (ROOT / "README.md").read_text()
