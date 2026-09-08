"""Run a streaming CLI (Claude Code, Codex) with a prompt on stdin, a hard timeout and clean teardown.

Shared by `claude_stream` and `codex_stream`: both CLIs write JSON lines to stdout, read the prompt from
stdin and must be killed as a process tree on timeout (the CLI spawns helpers that would otherwise keep our
pipes open). `run_streaming_cli` always returns after the process has exited, so files the CLI writes at
exit (Codex's `-o` answer file) are complete when it returns.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable


class PlannerError(RuntimeError):
    """The CLI failed, timed out, or returned no usable answer. `meta` carries backend metadata gathered
    before the failure (tool-use violations, usage) so a failed attempt is still accounted for."""

    def __init__(self, message: str, meta: dict[str, Any] | None = None):
        super().__init__(message)
        self.meta: dict[str, Any] = dict(meta or {})


@dataclass
class CliRun:
    result: Any                     # what `consume` returned, or None when it raised
    error: PlannerError | None      # consume's PlannerError, with timeout/stderr context added
    returncode: int | None
    stderr_tail: str
    timed_out: bool


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the CLI and any children holding our pipes; fall back to a direct kill."""
    if sys.platform == "win32":
        try:
            r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15)
            if r.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_streaming_cli(cmd: list[str], stdin_text: str, *, timeout: float,
                      consume: Callable[[Iterable[str]], Any], label: str, cwd: str | None = None) -> CliRun:
    """Start `cmd`, feed `stdin_text`, hand stdout's lines to `consume`, wait for exit.

    Raises PlannerError only when the process cannot be started. Anything `consume` raises as PlannerError
    is returned in `CliRun.error` (annotated with the timeout or the stderr tail); other exceptions propagate.
    """
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", shell=False, cwd=cwd)
    except (OSError, ValueError) as ex:
        raise PlannerError(f"could not start {cmd[0]}: {ex}") from None
    stderr_tail: deque[str] = deque(maxlen=20)
    stdin_error: list[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())

    def feed_stdin() -> None:
        # written from a worker so a chatty child cannot deadlock us on a full stdout pipe
        assert proc.stdin is not None
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        except OSError as ex:
            stdin_error.append(str(ex))

    threading.Thread(target=drain, daemon=True).start()
    threading.Thread(target=feed_stdin, daemon=True).start()
    timed_out = threading.Event()

    def on_timeout() -> None:
        timed_out.set()
        kill_tree(proc)

    timer = threading.Timer(timeout, on_timeout)
    timer.daemon = True
    timer.start()
    result: Any = None
    error: PlannerError | None = None
    try:
        assert proc.stdout is not None
        try:
            result = consume(proc.stdout)
        except PlannerError as ex:
            error = ex
    finally:
        timer.cancel()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass
    tail = " | ".join(stderr_tail)[-400:]
    if error is not None:
        if timed_out.is_set():
            error = PlannerError(f"{label} timed out after {timeout:.0f}s", error.meta)
        else:
            extra = f"; stdin: {stdin_error[0]}" if stdin_error else ""
            error = PlannerError(f"{error}{extra}{'; stderr: ' + tail if tail else ''}", error.meta)
    return CliRun(result, error, proc.returncode, tail, timed_out.is_set())
