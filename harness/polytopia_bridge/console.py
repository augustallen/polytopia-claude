"""Live terminal commentary for a game in progress. Stdlib only; sequential output, no redraws."""
from __future__ import annotations

import os
import sys
from collections import Counter
from typing import Any

from .observe import describe_matchup, enemy_capital, xy
from .planner import fmt_cost

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
FG = {"green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m", "cyan": "\033[36m",
      "magenta": "\033[35m", "grey": "\033[90m"}


def describe(a: dict[str, Any]) -> str:
    """Short human-readable form of an action dict."""
    k = a.get("kind", "?")
    if k == "end_turn":
        return "end turn"
    if k == "move":
        return f"move #{a.get('unit_id')} -> {xy(a['to'])}"
    if k == "attack":
        tgt = f"{a.get('target_type', 'unit')}#{a.get('target_unit_id', '?')} at {xy(a['target'])}"
        eff = ""
        if "damage" in a:
            eff = (f" (preview: deals {max(0, a['damage']):g}, takes {max(0, a.get('retaliation', 0)):g}"
                   f"{', kills' if a.get('kills') else ''})")
        return f"attack #{a.get('unit_id')} -> {tgt}{eff}"
    if k == "train":
        return f"train {a.get('unit_type')} at {xy(a['at'])} ({a.get('cost', '?')} stars)"
    if k == "build":
        return f"build {a.get('improvement')} at {xy(a['at'])} ({a.get('cost', '?')} stars)"
    if k == "research":
        return f"research {a.get('tech')} ({a.get('cost', '?')} stars)"
    if k == "city_reward":
        return f"city reward {a.get('reward')} at {xy(a['at'])}"
    if k == "peace_request_response":
        return f"{'accept' if a.get('accept') else 'decline'} peace with player {a.get('opponent')}"
    bits = [k.replace("_", " ")]
    if "unit_type" in a:
        bits.append(str(a["unit_type"]))
    if "unit_id" in a:
        bits.append(f"#{a['unit_id']}")
    if "at" in a:
        bits.append(f"at {xy(a['at'])}")
    if "opponent" in a:
        bits.append(f"with player {a['opponent']}")
    return " ".join(bits)


class Console:
    def __init__(self, color: bool = True, show_thinking: bool = True, stream=None, verbose: bool = False):
        self.out = stream or sys.stdout
        try:
            self.tty = bool(self.out.isatty())
        except (AttributeError, ValueError):
            self.tty = False
        self.color = color and self.tty
        self.show_thinking = show_thinking
        self.verbose = verbose
        self._thinking_open = False
        self._commentary_open = False
        self._thinking_tokens = 0
        self._thinking_announced = False
        if self.color and sys.platform == "win32":
            os.system("")   # enable ANSI escapes in the Windows console
        try:
            self.out.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    # ------------------------------------------------------------------ helpers

    def _c(self, s: str, *codes: str) -> str:
        if not self.color:
            return s
        return "".join(codes) + s + RESET

    def _w(self, s: str = "", end: str = "\n") -> None:
        self.out.write(s + end)
        self.out.flush()

    def _close_stream(self) -> None:
        if self._thinking_open or self._commentary_open:
            self._w()
        self._thinking_open = self._commentary_open = False

    # ------------------------------------------------------------------ events

    def banner(self, s: str) -> None:
        self._close_stream()
        self._w(self._c(s, BOLD, FG["cyan"]))

    def note(self, s: str) -> None:
        self._close_stream()
        self._w(self._c("  " + s, FG["grey"]))

    def warn(self, s: str) -> None:
        self._close_stream()
        self._w(self._c("  " + s, FG["red"]))

    def turn_header(self, msg: dict[str, Any], who: str | None = None) -> None:
        """`who` names the seat's planner in a two-agent game (printed before the tribe)."""
        self._close_stream()
        st = msg["state"]
        me = st["me"]
        s = st["settings"]
        my_cities = [c for c in st["cities"] if c["owner"] == me["id"]]
        my_units = [u for u in st["units"] if u["owner"] == me["id"]]
        enemy_units = [u for u in st["units"] if u["owner"] != me["id"]]
        enemy_cities = [c for c in st["cities"] if c["owner"] not in (me["id"], 0)]
        reported = sum(p.get("cities", 0) for p in st["players"] if p["id"] != me["id"] and p.get("alive", True))
        cap = enemy_capital(st)
        if cap:
            obj = f"enemy capital {cap['name']} at {xy((cap['x'], cap['y']))} lvl {cap['level']}"
        elif enemy_cities:
            obj = "remaining targets: " + ", ".join(f"{c['name']} at {xy((c['x'], c['y']))}" for c in enemy_cities)
        else:
            obj = "no enemy city located yet"
        comp = ", ".join(f"{t} x{n}" for t, n in Counter(u["type"] for u in enemy_units).most_common()) or "none"
        mine = ", ".join(f"{t} x{n}" for t, n in Counter(u["type"] for u in my_units).most_common()) or "none"
        self._w()
        seat = f"{who} as " if who else ""
        self._w(self._c(f"=== TURN {st['turn']} | {describe_matchup(st)} | "
                        f"{seat}{me['tribe']} (player {me['id']}): {me['stars']} stars (+{me['income']}) | {len(my_cities)} cities | units: {mine} ===",
                        BOLD, FG["cyan"]))
        self._w(self._c(f"    enemy: {reported} reported cities, {len(enemy_cities)} located | visible units: {comp} | {obj}",
                        FG["cyan"]))

    def map(self, text: str) -> None:
        self._close_stream()
        self._w(self._c(text, FG["grey"]))

    def enemy_turn(self, summary: str, who: str | None = None) -> None:
        self._close_stream()
        label = f"{who} moved" if who else "ENEMY TURN"
        self._w(self._c(f"  {label}: {summary}", FG["magenta"]))

    def plan_start(self, n: int, cap: int) -> None:
        self._close_stream()
        self._thinking_tokens = 0
        self._thinking_announced = False
        self._w(self._c(f"-- planning (model call {n} of {cap} this turn) ...", FG["magenta"]))

    def thinking(self, text: str, tokens: int | None = None) -> None:
        if not self.show_thinking:
            return
        if text:
            if not self._thinking_open:
                self.out.write(self._c("  thinking: ", DIM))
            self.out.write(self._c(text, DIM))
            self._thinking_open = True
        elif tokens is not None:
            # Claude Code hides thinking text and reports estimated tokens per chunk
            self._thinking_tokens += int(tokens)
            if self.tty:
                self.out.write("\r" + self._c(f"  thinking... ~{self._thinking_tokens} tokens", DIM))
                self._thinking_open = True
            elif not self._thinking_announced:
                self.out.write("  thinking...\n")
                self._thinking_announced = True
        self.out.flush()

    def commentary(self, delta: str) -> None:
        if not delta:
            return
        if not self._commentary_open:
            if self._thinking_open:
                self.out.write("\n")
                self._thinking_open = False
            self.out.write(self._c("  > ", BOLD, FG["yellow"]))
            self._commentary_open = True
        self.out.write(self._c(delta.replace("\n", "\n    "), FG["yellow"]))
        self.out.flush()

    def plan(self, plan, streamed: bool = True) -> None:
        """Print the parsed plan. `streamed=False` also prints the commentary (it did not arrive live)."""
        self._close_stream()
        if plan.error:
            self._w(self._c(f"  plan error: {plan.error}", FG["red"]))
        if not streamed and plan.commentary:
            self._w(self._c("  > " + plan.commentary.replace("\n", "\n    "), FG["yellow"]))
        head = f"  PLAN ({len(plan.steps)} action(s)"
        if plan.latency:
            head += f", {plan.latency:.1f}s"
        head += ")"
        if plan.steps and plan.steps[-1].get("kind") != "end_turn":
            head += " then ask again"
        summary = "; ".join(describe(a) for a in plan.steps) or "nothing"
        self._w(self._c(head + ": ", BOLD) + summary)
        for p in plan.problems:
            self._w(self._c(f"    ! {p}", FG["red"]))
        if self.verbose and plan.notes:
            self._w(self._c("  notes: " + plan.notes.replace("\n", " "), FG["grey"]))

    def step(self, action: dict[str, Any], result: dict[str, Any], dt: float, source: str = "plan") -> None:
        self._close_stream()
        tag = "" if source == "plan" else f"[{source}] "
        timing = self._c(f"({dt:.1f}s)", DIM) if self.verbose else ""
        if result.get("ok"):
            self._w(f"  {self._c('ok', FG['green'])}  {tag}{describe(action)}  {timing}".rstrip())
        else:
            self._w(f"  {self._c('!!', FG['red'])}  {tag}{describe(action)}  "
                    f"{self._c('REJECTED: ' + str(result.get('error')), FG['red'])}")

    def outcome(self, text: str) -> None:
        """What the engine reports after the last action (diff between the two states)."""
        self._close_stream()
        self._w(self._c(f"      => {text}", FG["grey"]))

    def skipped(self, action: dict[str, Any], reason: str = "no longer legal") -> None:
        self._close_stream()
        self._w(f"  {self._c('--', FG['grey'])}  {describe(action)}  {self._c('skipped: ' + reason, FG['grey'])}")

    def turn_footer(self, turn: int, actions: int, calls: int, latency: float, elapsed: float,
                    cost: float | None, total_cost: float | None, who: str | None = None,
                    violations: int = 0) -> None:
        self._close_stream()
        seat = f" ({who})" if who else ""
        if cost is None and total_cost is None:
            money = "cost n/a (subscription)"
        else:
            money = f"est {fmt_cost(cost)} this turn ({fmt_cost(total_cost)} so far)"
        bad = f", {violations} TOOL-USE VIOLATION(S)" if violations else ""
        self._w(self._c(f"--- turn {turn}{seat}: {actions} actions, {calls} model call(s), model {latency:.0f}s, "
                        f"wall {elapsed:.0f}s, {money}{bad}", FG["grey"]))

    def game_over(self, m: dict[str, Any], names: dict[int, str] | None = None) -> None:
        """Single agent: YOU WON / you lost. Two agents (`names` = player id -> planner name): the winner."""
        self._close_stream()
        winner = m.get("winner")
        if names:
            if winner in names:
                s = f"GAME OVER on turn {m.get('turn')}: WINNER {names[winner]} (player {winner})"
                colour = "green"
            else:
                s = f"GAME OVER on turn {m.get('turn')}: no winner reported (winner field {winner!r})"
                colour = "yellow"
        else:
            won = bool(m.get("won"))
            s = (f"GAME OVER on turn {m.get('turn')}: {'YOU WON' if won else 'you lost'} "
                 f"(winner player {winner}, score {m.get('score')})")
            colour = "green" if won else "red"
        self._w()
        self._w(self._c(s, BOLD, FG[colour]))
