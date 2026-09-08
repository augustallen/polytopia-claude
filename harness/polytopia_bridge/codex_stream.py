"""Backend for the OpenAI Codex CLI (`codex exec --json --output-schema ... -o ...`).

Recorded against codex-cli 0.153.4 on 2026-09-07 (tests/fixtures/codex_exec_sample.jsonl): the JSONL stream
carries whole items, not token deltas:
    {"type":"thread.started","thread_id":"..."}
    {"type":"item.completed","item":{"id":"item_0","type":"error","message":"Code Mode is unavailable ..."}}
    {"type":"turn.started"}
    {"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"{\"commentary\": ...}"}}
    {"type":"turn.completed","usage":{"input_tokens":16184,"cached_input_tokens":0,"cache_write_input_tokens":0,
                                      "output_tokens":304,"reasoning_output_tokens":136}}
The schema-conformant answer is written to the `-o` file at exit; that file is the answer of record.

Isolation: Codex runs with an empty working directory that holds only AGENTS.md (the game instructions, the
same text Claude gets as its system prompt) and the schema file. Its shell/browser/computer-use/image/skill
tool features are disabled on the command line and the user config is ignored (no MCP servers). Any tool item
that still shows up in the stream is counted as a violation; the runner voids the match on one.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from .subprocess_util import PlannerError, run_streaming_cli

Callback = Callable[[str], None] | None

DISABLED_FEATURES = ("shell_tool", "unified_exec", "view_image", "apps", "browser_use", "computer_use",
                     "image_generation", "skill_search", "sleep_tool", "tool_suggest", "code_mode_host",
                     "in_app_local_automation")
# item types that mean the model used a tool (anything but talking)
TOOL_ITEM_TYPES = {"command_execution", "mcp_tool_call", "web_search", "file_change", "tool_call", "function_call",
                   "local_shell_call", "custom_tool_call", "reasoning_tool_call", "image_view", "computer_call"}
NO_TOOLS_NOTE = "Answer directly from the observation; do not run commands or read files."


def find_codex(codex_cmd: str | None = None) -> str:
    """The Codex executable. Prefer the real binary over the npm `codex.cmd` shim, which routes argv through
    cmd.exe on Windows (and mangles quotes, carets and percent signs)."""
    if codex_cmd:
        return codex_cmd
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for base in (home / "tools" / "node" / "node_modules" / "@openai" / "codex",
                 home / "AppData" / "Roaming" / "npm" / "node_modules" / "@openai" / "codex"):
        if base.is_dir():
            for exe in base.rglob("codex.exe"):
                return str(exe)
    return shutil.which("codex") or "codex"


def prepare_work_dir(root: Path, instructions: str, schema: dict) -> Path:
    """An isolated working directory for one game: AGENTS.md (instructions) and the schema, nothing else."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text(instructions, encoding="utf-8")
    (root / "plan_schema.json").write_text(json.dumps(schema, indent=1), encoding="utf-8")
    return root


def build_command(*, codex_cmd: str, work_dir: Path, model: str, effort: str | None, answer_path: Path,
                  disable: Iterable[str] = DISABLED_FEATURES) -> list[str]:
    cmd = [codex_cmd, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
           "-s", "read-only", "-C", str(work_dir), "-m", model]
    if effort:
        cmd += ["-c", f"model_reasoning_effort={effort}"]     # no inner quotes: TOML fallback keeps the literal
    for feature in disable:
        cmd += ["--disable", feature]
    cmd += ["--output-schema", str(work_dir / "plan_schema.json"), "-o", str(answer_path), "-"]
    return cmd


def parse_events(lines: Iterable[str], *, on_status: Callback = None) -> dict[str, Any]:
    """Fold the JSONL stream into {usage, violations, messages, errors, tool_items}. Never raises."""
    usage: dict[str, int] = {}
    violations = 0
    tool_items: list[str] = []
    messages: list[str] = []
    errors: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        if t == "thread.started" and on_status:
            on_status("codex thread started")
        elif t in ("item.completed", "item.started", "item.updated"):
            item = d.get("item") or {}
            it = str(item.get("type", ""))
            if it == "agent_message":
                if t == "item.completed":
                    messages.append(str(item.get("text", "")))
            elif it == "error":
                errors.append(str(item.get("message", "")))
            elif it == "reasoning":
                if on_status and t == "item.completed":
                    on_status("codex reasoning")
            elif it in TOOL_ITEM_TYPES or "call" in it or "exec" in it or "command" in it:
                if t == "item.completed" or t == "item.started":
                    tool_items.append(it)
                    if t == "item.completed":
                        violations += 1
        elif t == "turn.completed":
            u = d.get("usage") or {}
            usage = {k: int(v) for k, v in u.items() if isinstance(v, (int, float))}
        elif t == "error":
            errors.append(str(d.get("message") or d))
    return {"usage": usage, "violations": violations, "tool_items": tool_items, "messages": messages, "errors": errors}


def anthropic_usage(codex_usage: dict[str, int]) -> dict[str, int]:
    """Codex counts cached tokens inside input_tokens; the planner keeps them apart like the Anthropic API."""
    total_in = int(codex_usage.get("input_tokens", 0))
    cached = int(codex_usage.get("cached_input_tokens", 0))
    return {
        "input_tokens": max(0, total_in - cached),
        "output_tokens": int(codex_usage.get("output_tokens", 0)),
        "cache_creation_input_tokens": int(codex_usage.get("cache_write_input_tokens", 0)),
        "cache_read_input_tokens": cached,
    }


def read_answer(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise PlannerError("codex exec wrote no answer file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        raise PlannerError(f"codex answer file is not valid JSON: {ex}") from None
    if not isinstance(data, dict):
        raise PlannerError("codex answer is not a JSON object")
    return data


def run_codex_exec(prompt: str, *, instructions: str, schema: dict, model: str, effort: str | None = None,
                   codex_cmd: str | None = None, work_dir: Path, timeout: float = 300,
                   on_status: Callback = None) -> dict[str, Any]:
    """One `codex exec` planning call. Returns the planner's runner-result contract:
    {structured_output, usage (Anthropic key names), total_cost_usd: None, meta{streamed, violations, backend}}.
    """
    exe = find_codex(codex_cmd)
    prepare_work_dir(work_dir, instructions, schema)
    answer_path = work_dir / f"answer-{uuid.uuid4().hex}.json"
    cmd = build_command(codex_cmd=exe, work_dir=work_dir, model=model, effort=effort, answer_path=answer_path)
    text = prompt if prompt.rstrip().endswith(NO_TOOLS_NOTE) else prompt.rstrip() + "\n\n" + NO_TOOLS_NOTE
    run = run_streaming_cli(cmd, text, timeout=timeout, consume=lambda lines: parse_events(lines, on_status=on_status),
                            label="codex exec")
    events = run.result or {"usage": {}, "violations": 0, "tool_items": [], "messages": [], "errors": []}
    meta = {"streamed": False, "violations": events["violations"], "backend": "codex",
            "tool_items": events["tool_items"], "codex_usage": events["usage"]}
    try:
        if run.error is not None:
            raise run.error
        if run.timed_out:
            raise PlannerError(f"codex exec timed out after {timeout:.0f}s")
        if run.returncode not in (0, None):
            detail = "; ".join(events["errors"][-2:]) or run.stderr_tail
            raise PlannerError(f"codex exec exited with {run.returncode}: {detail[:300]}")
        answer = read_answer(answer_path)
    except PlannerError as ex:
        raise PlannerError(str(ex), meta) from None
    finally:
        try:
            answer_path.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "structured_output": answer,
        "usage": anthropic_usage(events["usage"]),
        "total_cost_usd": None,
        "result": events["messages"][-1] if events["messages"] else json.dumps(answer),
        "meta": meta,
    }
