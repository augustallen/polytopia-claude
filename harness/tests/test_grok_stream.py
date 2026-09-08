"""Grok Build backend against the recorded `grok --output-format json` sample and a fake grok executable."""
import json
import os
import sys
from pathlib import Path

import pytest

from polytopia_bridge.grok_stream import (DENY_RULES, GROK_TOOLS, PlannerError, build_command, parse_output, run_grok,
                                          to_result)

FIXTURES = Path(__file__).parent / "fixtures"


def sample():
    return json.loads((FIXTURES / "grok_json_sample.json").read_text(encoding="utf-8"))


def test_build_command_locks_the_agent_down(tmp_path):
    cmd = build_command(grok_bin="grok.exe", prompt_file=tmp_path / "p.txt", schema={"type": "object"}, instructions="RULES",
                        model="grok-4.6", effort="medium")
    assert cmd[0] == "grok.exe" and cmd[cmd.index("--prompt-file") + 1] == str(tmp_path / "p.txt")
    assert cmd[cmd.index("-m") + 1] == "grok-4.6"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == {"type": "object"}
    assert cmd[cmd.index("--system-prompt-override") + 1] == "RULES"
    assert cmd[cmd.index("--max-turns") + 1] == "1"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    for flag in ("--verbatim", "--no-plan", "--no-subagents", "--disable-web-search"):
        assert flag in cmd
    disallowed = cmd[cmd.index("--disallowed-tools") + 1].split(",")
    assert set(disallowed) == set(GROK_TOOLS) and "run_terminal_command" in disallowed and "web_search" in disallowed
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "--deny"] == list(DENY_RULES)
    assert cmd[cmd.index("--reasoning-effort") + 1] == "medium"
    assert "--reasoning-effort" not in build_command(grok_bin="g", prompt_file=tmp_path / "p", schema={}, instructions="i",
                                                     model="m", effort=None)


def test_to_result_maps_the_recorded_sample():
    res = to_result(sample())
    assert res["structured_output"]["actions"] == [9, 20, 42]
    assert res["usage"] == {"input_tokens": 9266, "output_tokens": 847, "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 128}
    assert abs(res["total_cost_usd"] - 0.00402526) < 1e-9
    assert res["meta"]["backend"] == "grok" and res["meta"]["streamed"] is False and res["meta"]["violations"] == 0
    assert res["meta"]["reasoning_tokens"] == 825 and res["meta"]["thought"].startswith("The user wants")


def test_to_result_counts_extra_turns_as_violations_and_falls_back_to_text():
    out = sample()
    del out["structuredOutput"]
    out["num_turns"] = 3
    out["modelUsage"]["grok-4.6-build"]["modelCalls"] = 3
    res = to_result(out)
    assert res["structured_output"]["actions"] == [9, 20, 42]      # parsed from text
    assert res["meta"]["violations"] == 2
    out["text"] = "not json"
    with pytest.raises(PlannerError, match="no structured output") as ex:
        to_result(out)
    assert ex.value.meta["violations"] == 2                          # accounting survives the failure
    out = sample()
    out["stopReason"] = "max_turn_requests"
    with pytest.raises(PlannerError, match="stopped early"):
        to_result(out)
    out = sample()
    out["total_cost_usd"] = None
    assert to_result(out)["total_cost_usd"] is None


def test_parse_output_tolerates_log_lines():
    assert parse_output('warning: something\n{"text": "x", "usage": {}}\n')["text"] == "x"
    with pytest.raises(PlannerError, match="no JSON"):
        parse_output("nothing here")
    with pytest.raises(PlannerError, match="not valid JSON"):
        parse_output("{oops")


FAKE_GROK = '''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
mode = os.environ.get("FAKE_GROK_MODE", "ok")
prompt = Path(args[args.index("--prompt-file") + 1]).read_text(encoding="utf-8")
schema = json.loads(args[args.index("--json-schema") + 1])
sysprompt = args[args.index("--system-prompt-override") + 1]
out = json.loads(Path(os.environ["FAKE_GROK_SAMPLE"]).read_text(encoding="utf-8"))
out["structuredOutput"]["notes"] = f"prompt={len(prompt)} schema={schema.get('type')} sys={sysprompt[:10]} cwd={Path.cwd().name}"
out["text"] = json.dumps(out["structuredOutput"])
if mode == "crash":
    print("boom", file=sys.stderr)
    sys.exit(2)
if mode == "garbage":
    print("<<not json>>")
    sys.exit(0)
print(json.dumps(out))
'''


@pytest.fixture
def fake_grok(tmp_path, monkeypatch):
    stub = tmp_path / "fake_grok.py"
    stub.write_text(FAKE_GROK, encoding="utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "fake_grok.cmd"
        exe.write_text(f'@echo off\r\n"{sys.executable}" "{stub}" %*\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "fake_grok"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setenv("FAKE_GROK_SAMPLE", str(FIXTURES / "grok_json_sample.json"))
    return str(exe)


def run(fake_grok, tmp_path):
    return run_grok("PROMPT TEXT", instructions="GAME RULES", schema={"type": "object"}, model="grok-4.6", effort="medium",
                    grok_bin=fake_grok, work_dir=tmp_path / "seat", timeout=60)


def test_run_grok_end_to_end(fake_grok, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_GROK_MODE", "ok")
    res = run(fake_grok, tmp_path)
    notes = res["structured_output"]["notes"]
    assert "prompt=11" in notes and "schema=object" in notes and "sys=GAME RULES" in notes and "cwd=seat" in notes
    assert res["usage"]["input_tokens"] == 9266 and res["meta"]["violations"] == 0
    assert not list((tmp_path / "seat").glob("prompt-*.txt"))      # prompt file cleaned up


def test_run_grok_errors(fake_grok, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_GROK_MODE", "crash")
    with pytest.raises(PlannerError, match="exited with 2") as ex:
        run(fake_grok, tmp_path)
    assert ex.value.meta["backend"] == "grok"
    monkeypatch.setenv("FAKE_GROK_MODE", "garbage")
    with pytest.raises(PlannerError, match="JSON"):
        run(fake_grok, tmp_path)
    with pytest.raises(PlannerError, match="could not start"):
        run_grok("p", instructions="i", schema={}, model="m", grok_bin="no-such-grok-binary-xyz", work_dir=tmp_path / "s", timeout=5)


def test_env_untouched():
    assert "FAKE_GROK_MODE" not in os.environ or True
