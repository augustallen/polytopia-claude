"""Streaming backend for headless Claude Code (`claude -p --output-format stream-json`).

Claude Code implements `--json-schema` as a `StructuredOutput` tool call, so while the model writes its
answer the CLI emits `input_json_delta` events carrying the partial JSON. Thinking is streamed only as token
counts (the text is empty), so the live signal a viewer can read is the JSON itself. `CommentaryExtractor`
decodes the "commentary" string field of that JSON incrementally, which lets the runner print the model's
commentary while it is still being written.

Verified against Claude Code 2.1.261 on 2026-09-05: event lines look like
    {"type":"stream_event","event":{"type":"content_block_start","index":1,
        "content_block":{"type":"tool_use","name":"StructuredOutput","input":{}}}}
    {"type":"stream_event","event":{"type":"content_block_delta","index":1,
        "delta":{"type":"input_json_delta","partial_json":"{\"commentary\": \"I will ..."}}}
    {"type":"stream_event","event":{"type":"content_block_delta","index":0,
        "delta":{"type":"thinking_delta","thinking":"","estimated_tokens":150}}}
    {"type":"result","subtype":"success","is_error":false,"structured_output":{...},
        "usage":{"input_tokens":..,"output_tokens":..,"cache_creation_input_tokens":..,"cache_read_input_tokens":..},
        "total_cost_usd":0.05,"result":"<json text>"}
"""
from __future__ import annotations

import json
import re
import shutil
from typing import Any, Callable, Iterable

from .subprocess_util import PlannerError, kill_tree as _kill_tree, run_streaming_cli  # noqa: F401 (re-exported)

Callback = Callable[[str], None] | None
ThinkingCallback = Callable[[str, int | None], None] | None

STRUCTURED_OUTPUT_TOOL = "StructuredOutput"


class CommentaryExtractor:
    """Incrementally decode one string field (default "commentary") out of partial JSON text.

    feed() returns the newly decoded characters of that field ("" when nothing new is available), so a
    caller can print them as they arrive. Once the field's closing quote is seen, further chunks are ignored.
    """

    def __init__(self, field: str = "commentary"):
        self.field = field
        self._pattern = re.compile(r'"' + re.escape(field) + r'"\s*:\s*"')
        self.buf = ""
        self.started = False
        self.done = False
        self.emitted = ""
        self._start = -1

    def feed(self, chunk: str) -> str:
        if self.done or not chunk:
            return ""
        self.buf += chunk
        if not self.started:
            m = self._pattern.search(self.buf)
            if not m:
                return ""
            self.started = True
            self._start = m.end()
        raw = self.buf[self._start:]
        end = _find_unescaped_quote(raw)
        if end is not None:
            frag = raw[:end]
            self.done = True
        else:
            frag = _safe_prefix(raw)
        try:
            text = json.loads('"' + frag + '"')
        except json.JSONDecodeError:
            return ""
        if not text.startswith(self.emitted):
            self.emitted = text     # prefixes only grow; resync rather than print garbage
            return ""
        new = text[len(self.emitted):]
        self.emitted = text
        return new


def _find_unescaped_quote(s: str) -> int | None:
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i
        i += 1
    return None


def _safe_prefix(s: str) -> str:
    """Longest prefix of a partial JSON string body that decodes cleanly (no dangling escape)."""
    n = len(s) - len(s.rstrip("\\"))
    if n % 2 == 1:
        s = s[:-1]
    m = re.search(r"\\u[0-9a-fA-F]{0,3}$", s)
    if m:
        s = s[: m.start()]
    return s


def consume_events(lines: Iterable[str], extractor: CommentaryExtractor | None = None, *,
                   on_thinking: ThinkingCallback = None, on_text: Callback = None,
                   on_status: Callback = None) -> dict[str, Any]:
    """Parse stream-json lines; forward deltas to callbacks; return the final `result` event.

    Only the StructuredOutput tool block's JSON is fed to the extractor; plain text blocks are ignored (the
    model tends to repeat its commentary there). Raises PlannerError when the stream ends without a result or
    the result is an error.
    """
    extractor = extractor or CommentaryExtractor()
    tool_blocks: dict[Any, str] = {}      # content block index -> tool name
    structured_index: Any = None
    result: dict[str, Any] | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        if t == "stream_event":
            e = d.get("event") or {}
            et = e.get("type")
            if et == "content_block_start":
                cb = e.get("content_block") or {}
                if cb.get("type") == "tool_use":
                    tool_blocks[e.get("index")] = str(cb.get("name"))
                    if cb.get("name") == STRUCTURED_OUTPUT_TOOL:
                        if structured_index is not None and extractor.emitted and on_text:
                            # the model is answering a second time; the final result wins, but show the break
                            on_text("\n[revised] ")
                        structured_index = e.get("index")
                        extractor = CommentaryExtractor(extractor.field)   # fresh: only this block's JSON
                continue
            if et != "content_block_delta":
                continue
            delta = e.get("delta") or {}
            dt = delta.get("type")
            if dt == "thinking_delta":
                if on_thinking:
                    on_thinking(delta.get("thinking") or "", delta.get("estimated_tokens"))
            elif dt == "input_json_delta":
                idx = e.get("index")
                if structured_index is not None and idx != structured_index:
                    continue
                if structured_index is None and tool_blocks.get(idx) not in (None, STRUCTURED_OUTPUT_TOOL):
                    continue        # some other tool's arguments
                new = extractor.feed(delta.get("partial_json") or "")
                if new and on_text:
                    on_text(new)
            elif dt == "text_delta":
                continue    # spectator commentary comes from the StructuredOutput block only (plain text duplicated it)
        elif t == "system":
            if on_status and d.get("subtype") == "init":
                on_status(f"model {d.get('model')}")
        elif t == "result":
            result = d
    if result is None:
        raise PlannerError("claude -p ended without a result event")
    if result.get("is_error"):
        raise PlannerError(f"claude -p error: {str(result.get('result'))[:300]}")
    return result


def build_command(*, claude_bin: str, schema: dict, system_prompt: str, model: str, effort: str | None) -> list[str]:
    cmd = [claude_bin, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--json-schema", json.dumps(schema), "--system-prompt", system_prompt,
           "--tools", "", "--no-session-persistence", "--model", model]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def run_claude_stream(prompt: str, *, system_prompt: str, schema: dict, model: str, effort: str | None = None,
                      claude_bin: str = "claude", timeout: float = 300, on_thinking: ThinkingCallback = None,
                      on_text: Callback = None, on_status: Callback = None) -> dict[str, Any]:
    """Run one headless Claude Code request, streaming deltas to the callbacks; return the result event.

    The user prompt goes to stdin (Windows caps argv at ~32K chars); the system prompt and schema go on argv.
    A timer kills the whole process tree on timeout, which unblocks the stdout reader. The returned dict is
    the CLI's `result` event plus `meta` = {streamed, violations, backend} for the planner.
    """
    exe = shutil.which(claude_bin) or claude_bin
    cmd = build_command(claude_bin=exe, schema=schema, system_prompt=system_prompt, model=model, effort=effort)
    streamed = [False]

    def text_cb(s: str) -> None:
        streamed[0] = True
        if on_text:
            on_text(s)

    run = run_streaming_cli(
        cmd, prompt, timeout=timeout, label="claude -p",
        consume=lambda lines: consume_events(lines, on_thinking=on_thinking, on_text=text_cb if on_text else None,
                                             on_status=on_status))
    if run.error is not None:
        raise run.error
    result = run.result
    result["meta"] = {"streamed": streamed[0], "violations": 0, "backend": "claude-code"}
    return result
