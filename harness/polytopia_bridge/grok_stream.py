"""Backend for xAI's Grok Build CLI (`grok --prompt-file ... --json-schema ... --output-format json`).

Verified against grok 1.0.13 on 2026-09-08, signed in with the user's Grok subscription (the CLI talks to
`cli-chat-proxy.grok.com`; no API key). One headless call prints a single JSON object:
    {"text": "...", "stopReason": "end_turn", "sessionId": "...", "thought": "<reasoning summary>",
     "usage": {"input_tokens": N, "cache_read_input_tokens": N, "cache_creation_input_tokens": 0,
               "output_tokens": N, "reasoning_tokens": N, "total_tokens": N},
     "num_turns": 1, "total_cost_usd": 0.004, "modelUsage": {"grok-4.6-build": {..., "modelCalls": 1, "costUSD": ...}},
     "structuredOutput": {...}}          # present when --json-schema was given
The usage block already uses the Anthropic key names the planner expects. `total_cost_usd` is the CLI's
list-price estimate; the subscription pays for the call.

Isolation: the game instructions go in as `--system-prompt-override` (a real system message, like the
Claude seat); every built-in tool is removed with `--disallowed-tools`, web search is disabled, subagents
and plan mode are off, `--max-turns 1` forbids an agent loop, permission rules deny the tool families anyway,
and the working directory is an empty per-game folder. Any extra agent turn or model call is counted as a
tool-use violation; the runner voids the match on one.
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

# every built-in tool grok 1.0.13 lists in its streaming-json `available_commands` line
GROK_TOOLS = ("run_terminal_command", "run_terminal_cmd", "read_file", "search_replace", "list_dir", "grep",
              "kill_command_or_subagent", "todo_write", "get_command_or_subagent_output", "spawn_subagent",
              "scheduler_create", "scheduler_delete", "scheduler_list", "monitor", "search_tool", "use_tool",
              "workflow", "enter_plan_mode", "exit_plan_mode", "ask_user_question", "web_search", "web_fetch",
              "image_gen", "image_edit", "image_to_video", "reference_to_video", "write", "Agent")
DENY_RULES = ("Bash(*)", "Read(*)", "Edit(*)", "Write(*)", "Grep(*)", "Glob(*)", "WebFetch(*)", "WebSearch(*)")
DEFAULT_MODEL = "grok-4.6"


def find_grok(grok_bin: str | None = None) -> str:
    """The grok executable: an explicit path, PATH, or the installer's default location."""
    if grok_bin:
        return grok_bin
    on_path = shutil.which("grok")
    if on_path:
        return on_path
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    default = home / ".grok" / "bin" / ("grok.exe" if os.name == "nt" else "grok")
    return str(default) if default.exists() else "grok"


def build_command(*, grok_bin: str, prompt_file: Path, schema: dict, instructions: str, model: str,
                  effort: str | None) -> list[str]:
    cmd = [grok_bin, "--prompt-file", str(prompt_file), "-m", model, "--output-format", "json",
           "--json-schema", json.dumps(schema), "--system-prompt-override", instructions,
           "--verbatim", "--max-turns", "1", "--permission-mode", "dontAsk", "--no-plan", "--no-subagents",
           "--disable-web-search", "--disallowed-tools", ",".join(GROK_TOOLS)]
    for rule in DENY_RULES:
        cmd += ["--deny", rule]
    if effort:
        cmd += ["--reasoning-effort", effort]
    return cmd


def parse_output(stdout: str) -> dict[str, Any]:
    """The single JSON object grok prints in `json` mode (tolerates leading log lines)."""
    text = stdout.strip()
    start = text.find("{")
    if start < 0:
        raise PlannerError("grok printed no JSON object")
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError as ex:
        raise PlannerError(f"grok output is not valid JSON: {ex}") from None


def to_result(out: dict[str, Any]) -> dict[str, Any]:
    """Planner result contract from grok's json output."""
    usage_in = out.get("usage") or {}
    usage = {k: int(usage_in.get(k, 0) or 0) for k in
             ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    model_calls = sum(int((m or {}).get("modelCalls", 0) or 0) for m in (out.get("modelUsage") or {}).values())
    turns = int(out.get("num_turns", 1) or 1)
    violations = max(0, turns - 1, model_calls - 1)
    meta = {"streamed": False, "violations": violations, "backend": "grok",
            "stop_reason": out.get("stopReason"), "num_turns": turns, "model_calls": model_calls,
            "reasoning_tokens": int(usage_in.get("reasoning_tokens", 0) or 0),
            "thought": str(out.get("thought") or "")[:600]}
    answer = out.get("structuredOutput")
    text = str(out.get("text") or "")
    if not isinstance(answer, dict):
        try:
            answer = json.loads(text)
        except json.JSONDecodeError:
            raise PlannerError(f"grok answer has no structured output (stopReason {out.get('stopReason')}): {text[:200]}", meta)
    if out.get("stopReason") not in (None, "end_turn", "stop"):
        raise PlannerError(f"grok stopped early: {out.get('stopReason')}", meta)
    cost = out.get("total_cost_usd")
    return {"structured_output": answer, "usage": usage, "total_cost_usd": float(cost) if cost is not None else None,
            "result": text, "meta": meta}


def run_grok(prompt: str, *, instructions: str, schema: dict, model: str = DEFAULT_MODEL, effort: str | None = None,
             grok_bin: str | None = None, work_dir: Path, timeout: float = 300, on_status: Callback = None) -> dict[str, Any]:
    """One headless Grok Build planning call. Returns the planner's runner-result contract."""
    exe = find_grok(grok_bin)
    work_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = work_dir / f"prompt-{uuid.uuid4().hex}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    cmd = build_command(grok_bin=exe, prompt_file=prompt_file, schema=schema, instructions=instructions, model=model, effort=effort)
    lines: list[str] = []

    def consume(stream: Iterable[str]) -> None:
        if on_status:
            on_status("grok thinking")
        for line in stream:
            lines.append(line)

    try:
        run = run_streaming_cli(cmd, "", timeout=timeout, consume=consume, label="grok", cwd=str(work_dir))
        if run.error is not None:
            raise run.error
        if run.timed_out:
            raise PlannerError(f"grok timed out after {timeout:.0f}s")
        stdout = "".join(lines)
        if run.returncode not in (0, None):
            raise PlannerError(f"grok exited with {run.returncode}: {(run.stderr_tail or stdout)[-300:]}")
        return to_result(parse_output(stdout))
    except PlannerError as ex:
        meta = dict(ex.meta) if ex.meta else {}
        meta.setdefault("backend", "grok")
        meta.setdefault("streamed", False)
        meta.setdefault("violations", 0)
        raise PlannerError(str(ex), meta) from None
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except OSError:
            pass
