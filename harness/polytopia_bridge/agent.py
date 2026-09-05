"""Agents that map a bridge `state` message to one legal action.

ClaudeAgent: one Claude request per action. The request is
    system  = rules.md (cached)
    user    = observation text (map, cities, units, numbered legal actions, the agent's own
              running notes, and the last few actions with their results)
and the reply is structured JSON {reasoning, action, notes}. No transcript is carried between
requests: the notes field is the agent's memory across actions and turns, which keeps every request
small and the rules block cacheable.

RandomAgent: the baseline from PLAN.md phase 3 (uniform over legal actions, never disbands).
"""
from __future__ import annotations

import json
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .observe import render

RULES = (Path(__file__).parent / "rules.md").read_text(encoding="utf-8")
DEFAULT_MODEL = "claude-fable-5-1"
MAX_RECENT = 15

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "description": "2-4 sentences on why this action now."},
        "action": {"type": "integer", "description": "Index of the chosen legal action."},
        "notes": {"type": "string", "description": "Your updated running plan for the next turns (<= 120 words)."},
    },
    "required": ["reasoning", "action", "notes"],
    "additionalProperties": False,
}

# $ per million tokens: (input, output, cache write, cache read)
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 12.5, 0.25),
    "claude-fable-5": (10.0, 50.0, 12.5, 1.0),
    "claude-opus-5": (5.0, 25.0, 6.25, 0.5),
    "claude-sonnet-5": (2.0, 10.0, 2.5, 0.2),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.1),
}


@dataclass
class Decision:
    index: int
    reasoning: str
    notes: str
    usage: dict[str, int] = field(default_factory=dict)
    latency: float = 0.0
    raw: str = ""
    error: str | None = None


class RandomAgent:
    name = "random"
    AVOID = {"disband", "destroy", "break_peace", "resign"}

    def __init__(self, seed: int = 0, end_turn_prob: float = 0.1):
        self.rng = random.Random(seed)
        self.end_turn_prob = end_turn_prob
        self.total_usage: Counter = Counter()

    def decide(self, state_msg: dict[str, Any]) -> Decision:
        legal = state_msg["legal_actions"]
        candidates = [i for i, a in enumerate(legal) if a["kind"] not in self.AVOID]
        non_end = [i for i in candidates if legal[i]["kind"] != "end_turn"]
        if non_end and self.rng.random() > self.end_turn_prob:
            return Decision(self.rng.choice(non_end), "random", "")
        end = next((i for i, a in enumerate(legal) if a["kind"] == "end_turn"), candidates[0] if candidates else 0)
        return Decision(end, "random", "")

    def record(self, turn: int, action: dict, result: dict) -> None:
        pass

    def cost(self) -> float:
        return 0.0


class ClaudeAgent:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "medium", client=None, max_tokens: int = 4000):
        import anthropic  # imported here so RandomAgent works without the SDK

        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic()
        self.name = model
        self.notes = ""
        self.recent: list[str] = []
        self.total_usage: Counter = Counter()
        self.calls = 0

    # ------------------------------------------------------------------ prompt

    def build_prompt(self, state_msg: dict[str, Any], error: str | None = None) -> tuple[str, list]:
        text, legal = render(state_msg, notes=self.notes)
        parts = [text]
        if self.recent:
            parts.append("RECENT ACTIONS (most recent last):\n" + "\n".join(self.recent[-MAX_RECENT:]))
        if error:
            parts.append(f"YOUR PREVIOUS ANSWER WAS INVALID: {error}. Choose again from the numbered list.")
        parts.append("Choose exactly one action index from LEGAL ACTIONS.")
        return "\n\n".join(parts), legal

    def _request(self, prompt: str):
        params: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": RULES, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
        )
        if self.model.startswith("claude-fable"):
            # Fable: thinking is always on; server-side fallback covers a policy refusal.
            return self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        return self.client.messages.create(**params)

    # ------------------------------------------------------------------ decide

    def decide(self, state_msg: dict[str, Any]) -> Decision:
        legal = state_msg["legal_actions"]
        error = None
        for attempt in range(2):
            prompt, _ = self.build_prompt(state_msg, error)
            t0 = time.monotonic()
            response = self._request(prompt)
            latency = time.monotonic() - t0
            usage = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
                "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
                "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            }
            self.total_usage.update(usage)
            self.calls += 1

            if response.stop_reason == "refusal":
                error = "the model refused"
                break
            raw = next((b.text for b in response.content if b.type == "text"), "")
            try:
                data = json.loads(raw)
                index = int(data["action"])
                if not 0 <= index < len(legal):
                    raise ValueError(f"index {index} is out of range 0-{len(legal) - 1}")
                self.notes = str(data.get("notes", ""))[:1500]
                return Decision(index, str(data.get("reasoning", "")), self.notes, usage, latency, raw)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as ex:
                error = str(ex)
        # Two bad answers in a row: end the turn rather than stall the game.
        end = next((i for i, a in enumerate(legal) if a["kind"] == "end_turn"), 0)
        return Decision(end, "fallback after invalid answers", self.notes, error=error)

    def record(self, turn: int, action: dict, result: dict) -> None:
        summary = {k: v for k, v in action.items() if k in ("kind", "unit_id", "to", "target", "at", "unit_type", "improvement", "tech", "reward")}
        status = "ok" if result.get("ok") else f"REJECTED ({result.get('error')})"
        self.recent.append(f"turn {turn}: {json.dumps(summary)} -> {status}")

    def cost(self) -> float:
        p = PRICES.get(self.model)
        if not p:
            return 0.0
        u = self.total_usage
        return (u["input"] * p[0] + u["output"] * p[1] + u["cache_write"] * p[2] + u["cache_read"] * p[3]) / 1e6


class ClaudeCodeAgent(ClaudeAgent):
    """Same prompt and parsing as ClaudeAgent, but each decision runs Claude Code headless
    (`claude -p ... --json-schema ...`), so it uses the user's Claude subscription instead of API
    billing. Slower per decision (a CLI process per action, ~4-8 s) and without the `effort` knob;
    the reported cost is Claude Code's list-price estimate, not a charge."""

    def __init__(self, model: str = "claude-sonnet-5", claude_bin: str = "claude", timeout: float = 240, runner=None):
        self.model = model
        self.effort = None
        self.max_tokens = 0
        self.name = f"claude-code:{model}"
        self.notes = ""
        self.recent = []
        self.total_usage = Counter()
        self.calls = 0
        self.timeout = timeout
        self.list_cost = 0.0
        self._runner = runner or self._run_cli
        import shutil
        self.claude_bin = shutil.which(claude_bin) or claude_bin

    def _run_cli(self, prompt: str) -> dict:
        import subprocess
        cmd = [self.claude_bin, "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(DECISION_SCHEMA),
               "--system-prompt", RULES, "--tools", "", "--no-session-persistence", "--model", self.model]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=self.timeout)
        if proc.returncode != 0 and not proc.stdout.strip():
            raise RuntimeError(f"claude -p failed ({proc.returncode}): {proc.stderr.strip()[:300]}")
        return json.loads(proc.stdout)

    def _request(self, prompt: str):
        from types import SimpleNamespace

        d = self._runner(prompt)
        u = d.get("usage", {}) or {}
        self.list_cost += float(d.get("total_cost_usd") or 0.0)
        if d.get("is_error"):
            raise RuntimeError(f"claude -p error: {str(d.get('result'))[:300]}")
        text = json.dumps(d["structured_output"]) if d.get("structured_output") is not None else str(d.get("result", ""))
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(
                input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                cache_creation_input_tokens=u.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=u.get("cache_read_input_tokens", 0),
            ),
        )

    def cost(self) -> float:
        return self.list_cost
