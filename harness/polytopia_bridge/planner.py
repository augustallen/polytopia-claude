"""One model call per turn: the planner returns an ordered list of legal-action indices.

Legal-action indices are renumbered by the bridge after every action, so each planned index is resolved
to its action dict at plan time and re-located in the fresh legal list by `action_key` at execution time.
An action that is no longer legal (its tile got occupied, its target died) is skipped, not guessed, and
later steps for the same unit are dropped with it.

Convention for the model: a plan that ends with the end-turn action finishes the turn; a plan that omits it
means "run these, then ask me again" (used after research or a level-up unlocks new actions).
"""
from __future__ import annotations

import json
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .claude_stream import PlannerError, run_claude_stream
from .codex_stream import run_codex_exec
from .grok_stream import DEFAULT_MODEL as GROK_DEFAULT_MODEL, run_grok
from .observe import LEGEND, render, xy

HERE = Path(__file__).parent
RULES = (HERE / "rules.md").read_text(encoding="utf-8")
STRATEGY = (HERE / "strategy_domination.md").read_text(encoding="utf-8")
SYSTEM_PROMPT = RULES.rstrip() + "\n\n" + STRATEGY.rstrip() + "\n\nMap legend: " + LEGEND + "\n"
DEFAULT_MODEL = "claude-opus-5"

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "commentary": {
            "type": "string",
            "description": "Write this FIRST: 2-3 short sentences (max 70 words) for a spectator: the immediate objective, "
                           "the decisive action or spending choice and why, and the main threat or why another call is "
                           "needed. Do not repeat the action list. Attribute zero retaliation to the current preview, "
                           "range advantage or a killing blow, not to being an Archer; treat damage totals as estimates.",
        },
        "actions": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Ordered legal-action indices to execute now. End with the end-turn index unless you want "
                           "to be asked again after these run (e.g. after research unlocks a unit).",
        },
        "notes": {
            "type": "string",
            "description": "Your running plan for the next turns (<= 100 words); shown back to you next turn. Describe "
                           "unexecuted outcomes conditionally: do not record a planned kill, capture or purchase as done; "
                           "the next state and the execution log say what happened.",
        },
    },
    "required": ["commentary", "actions", "notes"],
    "additionalProperties": False,
}

# Fields that identify an action; derived fields (damage, kills, cost, unlocks...) are ignored.
KEY_FIELDS = ("kind", "unit_id", "to", "target", "target_unit_id", "at", "unit_type", "improvement", "tech",
              "reward", "opponent", "accept", "effect")
# Kinds that act on the unit standing at `at` without naming it; the plan remembers who stood there.
TILE_UNIT_KINDS = {"recover", "heal_others", "destroy", "disband", "promote", "examine_ruins", "freeze_area",
                   "break_ice", "stay", "explode", "boost", "decompose", "hide", "disembark", "flood", "swarm",
                   "upgrade", "capture"}

INSTRUCTIONS = (
    "Reply with: commentary (first), then the ordered list of action indices for this turn, then notes. "
    "Choose useful actions; do not execute actions merely because they are legal. Batch your chosen independent "
    "actions. Every index belongs to THIS snapshot: all spending shares one treasury (budget cumulatively from the "
    "latest reported spendable stars; never add income speculatively; re-budget after a refreshed state or a "
    "reward), and a destination that is blocked now has no selectable move even "
    "if an earlier action will free it. Check the ordered plan for conflicts: at most one recruit per city tile "
    "(training occupies the tile) and one placement per monument; do not give a unit two ordinary moves or send two "
    "units to the same destination unless the first leaves legally. Earlier attacks can kill a target sooner than "
    "its preview suggests; a skipped excess attack does not spend that attacker's action. Before moving a unit, "
    "consider the attacks currently available to it. Leave supporting units uncommitted when newly revealed enemies "
    "could change their best action. Omit the end-turn index only when you can name a useful follow-up that needs a "
    "fresh list (training after research, attacking after moving into range, occupying a cleared city); batch the "
    "enabling actions before that refresh. If an affordable research chain unlocks the unit needed for the current "
    "fight, use the remaining calls to complete the chain and recruit this turn; keep its intended city tile free "
    "and do not fill it with a substitute unit first. Do not end the turn merely because the next prerequisite or "
    "recruitment needs a refreshed list. Before assigning recover or leaving a combat unit idle, check whether it can "
    "help save a city or complete a kill, including after a move and a refresh; reassess recurring healing or staging "
    "plans when the enemy reply undoes their benefit. On your last call, prioritise executable combat, occupation and spending: "
    "anything unlocked afterwards waits until next turn. The current state and action list override earlier notes. "
    "An empty list ends the turn."
)


def _hashable(v: Any) -> Any:
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(x)) for k, x in v.items()))
    return v


def action_key(a: dict[str, Any]) -> tuple:
    return tuple((k, _hashable(a[k])) for k in KEY_FIELDS if k in a)


def find_action(legal: list[dict[str, Any]], key: tuple) -> int | None:
    for i, a in enumerate(legal):
        if action_key(a) == key:
            return i
    return None


def end_turn_index(legal: list[dict[str, Any]]) -> int | None:
    return next((i for i, a in enumerate(legal) if a["kind"] == "end_turn"), None)


def step_unit(step: dict[str, Any]) -> int | None:
    """The unit a step acts with, if any (explicit id, or the plan-time occupant of its tile)."""
    u = step.get("unit_id")
    if u is None:
        u = step.get("_unit")
    return u


def annotate(steps: list[dict[str, Any]], state: dict[str, Any]) -> None:
    """Record the plan-time occupant for tile-addressed unit actions so execution can verify it."""
    units_at = {(u["x"], u["y"]): u["id"] for u in state.get("units", [])}
    for s in steps:
        if "unit_id" not in s and s.get("kind") in TILE_UNIT_KINDS and "at" in s:
            occ = units_at.get(tuple(s["at"]))
            if occ is not None:
                s["_unit"] = occ


def locate(step: dict[str, Any], msg: dict[str, Any]) -> tuple[int | None, str]:
    """Find a planned step in a fresh state's legal list. Returns (index, reason-if-missing)."""
    legal = msg["legal_actions"]
    idx = find_action(legal, action_key(step))
    if idx is None:
        return None, "no longer legal"
    if "_unit" in step:
        units_at = {(u["x"], u["y"]): u["id"] for u in msg["state"].get("units", [])}
        occ = units_at.get(tuple(step["at"]))
        if occ != step["_unit"]:
            return None, f"unit #{step['_unit']} is no longer at {xy(step['at'])}"
    return idx, ""


def depends_on(step: dict[str, Any], failed: dict[str, Any]) -> bool:
    """Later steps that use the same unit as a failed step are assumed to depend on it."""
    u, f = step_unit(step), step_unit(failed)
    return u is not None and u == f


def resolve_plan(indices: Any, legal: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Map the model's indices to (copies of) action dicts. Bad indices are reported, not guessed."""
    steps: list[dict[str, Any]] = []
    problems: list[str] = []
    if not isinstance(indices, list):
        return steps, [f"'actions' must be a list, got {type(indices).__name__}"]
    for n, raw in enumerate(indices):
        if type(raw) is not int:
            problems.append(f"action #{n + 1} is not an integer index: {raw!r}")
            continue
        if not 0 <= raw < len(legal):
            problems.append(f"action #{n + 1}: index {raw} does not exist (valid 0-{len(legal) - 1})")
            continue
        a = dict(legal[raw])
        steps.append(a)
        if a["kind"] == "end_turn":
            rest = len(indices) - n - 1
            if rest:
                problems.append(f"{rest} action(s) listed after end turn were dropped")
            break
    return steps, problems


@dataclass
class Plan:
    commentary: str
    notes: str
    steps: list[dict[str, Any]]
    problems: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    latency: float = 0.0
    cost: float | None = 0.0            # None when the backend reports no cost (subscription CLI)
    error: str | None = None
    attempts: int = 0
    raw: Any = None                      # the model's answer only
    meta: dict[str, Any] = field(default_factory=dict)   # backend metadata: streamed, violations, backend


def add_cost(a: float | None, b: float | None) -> float | None:
    """Sum two costs where None means unknown; unknown poisons the total."""
    if a is None or b is None:
        return None
    return a + b


def fmt_cost(c: float | None) -> str:
    return "n/a (subscription)" if c is None else f"${c:.2f}"


Runner = Callable[[str, Any, Any], dict[str, Any]]   # (prompt, on_thinking, on_text) -> result event


class TurnPlanner:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str | None = "medium", claude_bin: str = "claude",
                 timeout: float = 300, runner: Runner | None = None, on_thinking=None, on_commentary=None,
                 system_prompt: str = SYSTEM_PROMPT):
        self.model = model
        self.effort = effort
        self.claude_bin = claude_bin
        self.timeout = timeout
        self.system_prompt = system_prompt
        self.name = f"claude-code-{model}"
        self.notes = ""
        self.total_usage: Counter = Counter()
        self.calls = 0
        self.list_cost: float | None = 0.0
        self.violations = 0
        self.on_thinking = on_thinking
        self.on_commentary = on_commentary
        self._runner: Runner = runner or self._run_cli

    # ------------------------------------------------------------------ prompt

    def build_prompt(self, state_msg: dict[str, Any], turn_log: list[str] | None = None,
                     error: str | None = None, calls_left: int | None = None) -> tuple[str, list[dict[str, Any]]]:
        text, legal = render(state_msg, notes=self.notes, legend=False)
        parts = [text]
        if turn_log:
            parts.append("THIS TURN SO FAR (in order):\n" + "\n".join(turn_log[-40:]))
        if error:
            parts.append(f"YOUR PREVIOUS ANSWER WAS INVALID: {error}. Answer again using indices from the list above.")
        tail = INSTRUCTIONS
        if calls_left is not None:
            tail += (f" You have {calls_left} model call(s) left this turn including this one"
                     + ("; the turn ends after this plan." if calls_left <= 1 else "."))
        parts.append(tail)
        return "\n\n".join(parts), legal

    def _run_cli(self, prompt: str, on_thinking, on_text) -> dict[str, Any]:
        return run_claude_stream(prompt, system_prompt=self.system_prompt, schema=PLAN_SCHEMA, model=self.model,
                                 effort=self.effort, claude_bin=self.claude_bin, timeout=self.timeout,
                                 on_thinking=on_thinking, on_text=on_text)

    # ------------------------------------------------------------------ plan

    def plan(self, state_msg: dict[str, Any], turn_log: list[str] | None = None, *,
             max_attempts: int = 2, calls_left: int | None = None) -> Plan:
        """Ask for this turn's plan. Every CLI attempt (including retries after an invalid answer) counts
        against `max_attempts`; when they are exhausted the plan falls back to ending the turn.
        `calls_left` is the turn's remaining call budget as told to the model (defaults to max_attempts)."""
        legal = state_msg["legal_actions"]
        error: str | None = None
        attempts = 0
        usage_sum: Counter = Counter()
        latency_sum = 0.0
        cost_sum: float | None = 0.0
        meta_sum: dict[str, Any] = {"streamed": False, "violations": 0, "backend": None}

        def absorb(meta: dict[str, Any] | None) -> None:
            if not meta:
                return
            meta_sum["streamed"] = meta_sum["streamed"] or bool(meta.get("streamed"))
            v = int(meta.get("violations") or 0)
            meta_sum["violations"] += v
            self.violations += v
            meta_sum["backend"] = meta.get("backend") or meta_sum["backend"]
            for k, val in meta.items():
                if k not in ("streamed", "violations", "backend"):
                    meta_sum[k] = val

        budget = max_attempts if calls_left is None else calls_left
        while attempts < max(1, max_attempts):
            attempts += 1
            prompt, _ = self.build_prompt(state_msg, turn_log, error, calls_left=max(1, budget - attempts + 1))
            t0 = time.monotonic()
            self.calls += 1
            try:
                result = self._runner(prompt, self.on_thinking, self.on_commentary)
            except PlannerError as ex:
                error = str(ex)
                latency_sum += time.monotonic() - t0
                absorb(getattr(ex, "meta", None))
                continue
            latency_sum += time.monotonic() - t0
            absorb(result.get("meta"))
            u = result.get("usage") or {}
            usage = {
                "input": int(u.get("input_tokens", 0) or 0),
                "output": int(u.get("output_tokens", 0) or 0),
                "cache_write": int(u.get("cache_creation_input_tokens", 0) or 0),
                "cache_read": int(u.get("cache_read_input_tokens", 0) or 0),
            }
            raw_cost = result.get("total_cost_usd", 0.0)
            cost: float | None = None if raw_cost is None else float(raw_cost or 0.0)
            self.total_usage.update(usage)
            usage_sum.update(usage)
            self.list_cost = add_cost(self.list_cost, cost)
            cost_sum = add_cost(cost_sum, cost)
            data = result.get("structured_output")
            if data is None:
                try:
                    data = json.loads(str(result.get("result", "")))
                except json.JSONDecodeError:
                    error = "no structured output in the reply"
                    continue
            if not isinstance(data, dict) or "actions" not in data:
                error = "reply is missing 'actions'"
                continue
            steps, problems = resolve_plan(data.get("actions"), legal)
            if not steps and data.get("actions"):
                error = "; ".join(problems) or "no valid action indices"
                continue
            annotate(steps, state_msg["state"])
            self.notes = str(data.get("notes", ""))[:1500]
            return Plan(str(data.get("commentary", "")), self.notes, steps, problems, dict(usage_sum),
                        latency_sum, cost_sum, None, attempts, data, dict(meta_sum))
        end = end_turn_index(legal)
        steps = [dict(legal[end])] if end is not None else []
        return Plan("(fallback: ending the turn after invalid answers)", self.notes, steps, [], dict(usage_sum),
                    latency_sum, cost_sum, error, attempts, None, dict(meta_sum))

    def cost(self) -> float | None:
        """Total list-price cost so far; None once any call came from a backend without cost reporting."""
        return self.list_cost


class CodexPlanner(TurnPlanner):
    """Same turn contract as TurnPlanner, answered by the OpenAI Codex CLI (`codex exec`).

    The game instructions go to Codex as AGENTS.md in an isolated working directory (Codex has no
    system-prompt flag); the user prompt is byte-identical to Claude's. Codex streams no token deltas, so
    there is no live commentary: the runner prints it once the plan arrives (`Plan.meta["streamed"]`).
    """

    def __init__(self, model: str = "gpt-6-astra", effort: str | None = "medium", codex_cmd: str | None = None,
                 timeout: float = 300, runner: Runner | None = None, on_thinking=None,
                 system_prompt: str = SYSTEM_PROMPT, work_dir: Path | str | None = None):
        super().__init__(model, effort, timeout=timeout, runner=runner, on_thinking=on_thinking,
                         on_commentary=None, system_prompt=system_prompt)
        self.name = f"codex-{model}"
        self.codex_cmd = codex_cmd
        self.list_cost = None       # the Codex CLI reports tokens, not money
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="codex-seat-"))

    def _run_cli(self, prompt: str, on_thinking, on_text) -> dict[str, Any]:
        def status(s: str) -> None:
            if on_thinking:
                on_thinking("", None)   # keeps the console's progress line alive without claiming tokens
        return run_codex_exec(prompt, instructions=self.system_prompt, schema=PLAN_SCHEMA, model=self.model,
                              effort=self.effort, codex_cmd=self.codex_cmd, work_dir=self.work_dir,
                              timeout=self.timeout, on_status=status)


class GrokPlanner(TurnPlanner):
    """Same turn contract, answered by xAI's Grok Build CLI (`grok --prompt-file ... --json-schema ...`) on the
    user's Grok subscription. The instructions go in as a system-prompt override (a real system message, like
    the Claude seat); every built-in tool is removed and the agent loop is capped at one turn. No live
    commentary: the CLI prints one JSON object at the end."""

    def __init__(self, model: str = GROK_DEFAULT_MODEL, effort: str | None = "medium", grok_bin: str | None = None,
                 timeout: float = 300, runner: Runner | None = None, on_thinking=None,
                 system_prompt: str = SYSTEM_PROMPT, work_dir: Path | str | None = None):
        super().__init__(model, effort, timeout=timeout, runner=runner, on_thinking=on_thinking,
                         on_commentary=None, system_prompt=system_prompt)
        self.name = f"grok-{model}"
        self.grok_bin = grok_bin
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="grok-seat-"))

    def _run_cli(self, prompt: str, on_thinking, on_text) -> dict[str, Any]:
        def status(s: str) -> None:
            if on_thinking:
                on_thinking("", None)
        return run_grok(prompt, instructions=self.system_prompt, schema=PLAN_SCHEMA, model=self.model,
                        effort=self.effort, grok_bin=self.grok_bin, work_dir=self.work_dir, timeout=self.timeout,
                        on_status=status)


def make_planner(spec: str, *, timeout: float = 300, on_thinking=None, on_commentary=None,
                 work_root: Path | str | None = None, system_prompt: str = SYSTEM_PROMPT) -> TurnPlanner:
    """Build a fresh planner from "claude:<model>[:<effort>]", "codex:<model>[:<effort>]" or "grok:<model>[:<effort>]".

    Always a new instance: two seats must never share notes, usage or cost, even Claude-vs-Claude.
    """
    parts = spec.split(":")
    backend = parts[0].strip().lower()
    model = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    effort = parts[2].strip().lower() if len(parts) > 2 and parts[2].strip() else "medium"
    if backend in ("claude", "claude-code"):
        return TurnPlanner(model or DEFAULT_MODEL, effort, timeout=timeout, on_thinking=on_thinking,
                           on_commentary=on_commentary, system_prompt=system_prompt)
    if backend == "codex":
        work_dir = None
        if work_root is not None:
            work_dir = Path(work_root) / f"codex-{uuid.uuid4().hex[:8]}"
        return CodexPlanner(model or "gpt-6-astra", effort, timeout=timeout, on_thinking=on_thinking,
                            system_prompt=system_prompt, work_dir=work_dir)
    if backend == "grok":
        work_dir = None
        if work_root is not None:
            work_dir = Path(work_root) / f"grok-{uuid.uuid4().hex[:8]}"
        return GrokPlanner(model or GROK_DEFAULT_MODEL, effort, timeout=timeout, on_thinking=on_thinking,
                           system_prompt=system_prompt, work_dir=work_dir)
    raise ValueError(f"unknown planner backend {backend!r} in {spec!r} (use claude:<model>, codex:<model> or grok:<model>)")
