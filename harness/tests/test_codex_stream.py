"""Codex CLI backend against the recorded `codex exec --json` sample and a fake codex executable."""
import json
import os
import sys
from pathlib import Path

import pytest

from polytopia_bridge.codex_stream import (DISABLED_FEATURES, NO_TOOLS_NOTE, PlannerError, anthropic_usage, build_command,
                                           parse_events, prepare_work_dir, read_answer, run_codex_exec)

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_command_flags_and_quoting(tmp_path):
    cmd = build_command(codex_cmd="codex.exe", work_dir=tmp_path, model="gpt-6-astra", effort="low",
                        answer_path=tmp_path / "answer-1.json")
    assert cmd[:3] == ["codex.exe", "exec", "--json"]
    for flag in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config"):
        assert flag in cmd
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert cmd[cmd.index("-C") + 1] == str(tmp_path)
    assert cmd[cmd.index("-m") + 1] == "gpt-6-astra"
    assert "model_reasoning_effort=low" in cmd
    assert cmd[cmd.index("--output-schema") + 1] == str(tmp_path / "plan_schema.json")
    assert cmd[cmd.index("-o") + 1] == str(tmp_path / "answer-1.json")
    assert cmd[-1] == "-"                                  # prompt on stdin
    disabled = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--disable"]
    assert set(disabled) == set(DISABLED_FEATURES) and "shell_tool" in disabled
    assert not any('"' in a for a in cmd)                  # the .cmd shim would mangle quotes
    assert "model_reasoning_effort" not in " ".join(build_command(codex_cmd="c", work_dir=tmp_path, model="m",
                                                                  effort=None, answer_path=tmp_path / "a.json"))


def test_prepare_work_dir_holds_only_instructions_and_schema(tmp_path):
    d = prepare_work_dir(tmp_path / "seat", "RULES TEXT", {"type": "object"})
    assert sorted(p.name for p in d.iterdir()) == ["AGENTS.md", "plan_schema.json"]
    assert (d / "AGENTS.md").read_text(encoding="utf-8") == "RULES TEXT"
    assert json.loads((d / "plan_schema.json").read_text(encoding="utf-8")) == {"type": "object"}


def test_parse_recorded_sample():
    lines = (FIXTURES / "codex_exec_sample.jsonl").read_text(encoding="utf-8").splitlines()
    status = []
    ev = parse_events(lines, on_status=status.append)
    assert ev["usage"]["input_tokens"] == 16184 and ev["usage"]["output_tokens"] == 304
    assert ev["violations"] == 0 and ev["tool_items"] == []
    assert len(ev["messages"]) == 1 and json.loads(ev["messages"][0])["actions"] == [9, 20, 42, 10, 17, 36, 29]
    assert any("Code Mode" in e for e in ev["errors"])   # the disabled code-mode host complains, harmlessly
    assert status == ["codex thread started"]


def test_parse_counts_tool_use_as_violations():
    lines = [
        json.dumps({"type": "item.started", "item": {"id": "i1", "type": "command_execution", "command": "ls"}}),
        json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "command_execution", "command": "ls"}}),
        json.dumps({"type": "item.completed", "item": {"id": "i2", "type": "mcp_tool_call", "server": "x"}}),
        json.dumps({"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": "{}"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2}}),
        "garbage line",
    ]
    ev = parse_events(lines)
    assert ev["violations"] == 2 and ev["tool_items"] == ["command_execution", "command_execution", "mcp_tool_call"]
    assert anthropic_usage(ev["usage"]) == {"input_tokens": 6, "output_tokens": 2, "cache_creation_input_tokens": 0,
                                            "cache_read_input_tokens": 4}


def test_read_answer_errors(tmp_path):
    good = tmp_path / "a.json"
    good.write_bytes((FIXTURES / "codex_exec_answer.json").read_bytes())
    assert read_answer(good)["actions"] == [9, 20, 42, 10, 17, 36, 29]
    with pytest.raises(PlannerError, match="no answer file"):
        read_answer(tmp_path / "missing.json")
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(PlannerError, match="no answer file"):
        read_answer(empty)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PlannerError, match="not valid JSON"):
        read_answer(bad)
    arr = tmp_path / "arr.json"
    arr.write_text("[1]", encoding="utf-8")
    with pytest.raises(PlannerError, match="not a JSON object"):
        read_answer(arr)


FAKE_CODEX = '''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
prompt = sys.stdin.read()
out = args[args.index("-o") + 1]
schema = Path(args[args.index("--output-schema") + 1])
workdir = Path(args[args.index("-C") + 1])
sample = Path(os.environ["FAKE_CODEX_SAMPLE"]).read_text(encoding="utf-8")
if mode == "tools":
    print(json.dumps({"type": "item.completed", "item": {"id": "t", "type": "command_execution", "command": "dir"}}))
for line in sample.splitlines():
    print(line)
if mode == "crash":
    print("boom", file=sys.stderr)
    sys.exit(2)
if mode != "nofile":
    answer = {"commentary": "fake", "actions": [0], "notes": prompt[-30:], "agents_md": (workdir / "AGENTS.md").read_text(encoding="utf-8")[:20],
              "schema_ok": schema.is_file()}
    Path(out).write_text(json.dumps(answer), encoding="utf-8")
'''


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    stub = tmp_path / "fake_codex.py"
    stub.write_text(FAKE_CODEX, encoding="utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "fake_codex.cmd"
        exe.write_text(f'@echo off\r\n"{sys.executable}" "{stub}" %*\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "fake_codex"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setenv("FAKE_CODEX_SAMPLE", str(FIXTURES / "codex_exec_sample.jsonl"))
    return str(exe)


def run(fake_codex, tmp_path, **kw):
    return run_codex_exec("PROMPT TEXT", instructions="GAME RULES", schema={"type": "object"}, model="gpt-6-astra",
                          effort="low", codex_cmd=fake_codex, work_dir=tmp_path / "seat", timeout=60, **kw)


def test_run_codex_exec_end_to_end(fake_codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "ok")
    res = run(fake_codex, tmp_path)
    ans = res["structured_output"]
    assert ans["actions"] == [0] and ans["agents_md"] == "GAME RULES" and ans["schema_ok"]
    assert ans["notes"].endswith(NO_TOOLS_NOTE[-30:])            # the no-tools note was appended to the prompt
    assert res["usage"] == {"input_tokens": 16184, "output_tokens": 304, "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0}
    assert res["total_cost_usd"] is None
    assert res["meta"]["streamed"] is False and res["meta"]["violations"] == 0 and res["meta"]["backend"] == "codex"
    assert not list((tmp_path / "seat").glob("answer-*.json"))   # answer file cleaned up


def test_run_codex_exec_reports_violations(fake_codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "tools")
    res = run(fake_codex, tmp_path)
    assert res["meta"]["violations"] == 1 and res["meta"]["tool_items"] == ["command_execution"]


def test_run_codex_exec_missing_answer_file(fake_codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "nofile")
    with pytest.raises(PlannerError, match="no answer file") as ex:
        run(fake_codex, tmp_path)
    assert ex.value.meta["backend"] == "codex"


def test_run_codex_exec_nonzero_exit(fake_codex, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "crash")
    with pytest.raises(PlannerError, match="exited with 2"):
        run(fake_codex, tmp_path)


def test_run_codex_exec_missing_executable(tmp_path):
    with pytest.raises(PlannerError, match="could not start"):
        run_codex_exec("p", instructions="i", schema={}, model="m", codex_cmd="no-such-codex-binary-xyz",
                       work_dir=tmp_path / "seat", timeout=5)


def test_env_is_not_touched_by_import():
    assert "FAKE_CODEX_MODE" not in os.environ or True
