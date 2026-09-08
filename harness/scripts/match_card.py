#!/usr/bin/env python3
"""Render a Polytopia-style stats card (PNG) for one deathmatch log.

    match_card.py logs/20260907-213529-deathmatch-....jsonl --out ../docs/samples/game5-card.png

One image for posting instead of a video: the game's sunset menu look, the end-screen leader board, and
small-multiple charts (stars, income, score, cities, units per turn) for the two seats, plus a row of
stat tiles (model calls, median call time, units lost, captures, cost). Everything is read from the log
(`turn`, `decision`, `plan`, `game_over`, `summary` events), so it works for any two-seat game.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

# The game's start-screen sunset, sampled from a captured frame; chart surface and text from the dataviz palette.
SKY_TOP, SKY_BOTTOM = "#f04f7c", "#f7a35c"
SURFACE, GRID, TEXT, TEXT2 = "#fcfcfb", "#e6e5e1", "#0b0b0b", "#52514e"
SERIES = {"claude": "#eb6834", "codex": "#2a78d6", "grok": "#1baf7a"}   # categorical slots 2, 1, 3 (validated pairs)
GREENS = ["#4fae55", "#63c064", "#3f9c4b", "#79cc73", "#57b75c"]
WATER = ["#7fd0ea", "#9adcf0", "#6fc5e5"]
W, H = 2000, 2500                                        # px, 4:5 portrait


# ------------------------------------------------------------------ data

def display_name(planner: str) -> tuple[str, str]:
    """('Claude Fable 5.1', 'claude') from 'claude-code-claude-fable-5-1'; ('Codex gpt-6-astra', 'codex')."""
    if planner.startswith("claude-code-"):
        parts = planner[len("claude-code-"):].split("-")
        if parts and parts[0] == "claude":
            parts = parts[1:]
        words = [parts[0].capitalize()] if parts else ["Claude"]
        digits = [p for p in parts[1:] if p.isdigit()]
        if digits:
            words.append(".".join(digits))
        return "Claude " + " ".join(words), "claude"
    if planner.startswith("codex-"):
        return "Codex " + planner[len("codex-"):], "codex"
    if planner.startswith("grok-"):
        model = planner[len("grok-"):]
        if model.startswith("grok-"):
            model = model[len("grok-"):]          # "grok-4.6" -> "4.6"
        return "Grok " + model, "grok"
    return planner, "claude"


def load_match(path: Path) -> dict:
    recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    players: dict[int, dict] = {}
    order: list[int] = []
    for r in recs:
        if r["event"] == "turn":
            pid = r["player"]
            if pid not in players:
                players[pid] = {"planner": r["planner"], "turns": {}, "captures": [], "latency": []}
                order.append(pid)
            players[pid]["turns"][r["turn"]] = {k: r[k] for k in ("score", "stars", "income", "cities", "units")}
        elif r["event"] == "decision" and r["action"].get("kind") == "capture":
            players.setdefault(r["player"], {"planner": r.get("planner", "?"), "turns": {}, "captures": [], "latency": []})
            players[r["player"]]["captures"].append(r["turn"])
        elif r["event"] == "plan":
            players.setdefault(r["player"], {"planner": r.get("planner", "?"), "turns": {}, "captures": [], "latency": []})
            players[r["player"]]["latency"].append(r["latency"])
    game_over = next((r for r in recs if r["event"] == "game_over"), None)
    summary = next((r for r in recs if r["event"] == "summary"), None)
    seats = {s["player"]: s for s in (summary or {}).get("seats", [])}
    final = {p["id"]: p for p in (game_over or {}).get("players", [])}
    for pid, p in players.items():
        p["name"], p["backend"] = display_name(p["planner"])
        p["short"] = p["name"].split(" ", 1)[1]
        p["seat"] = seats.get(pid, {})
        p["final"] = final.get(pid, {})
        p["kills"] = p["final"].get("kills", 0)
        p["median_latency"] = statistics.median(p["latency"]) if p["latency"] else None
    winner = (game_over or {}).get("winner")
    stamp = path.name[:8]
    date = f"{stamp[6:8]} {['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][int(stamp[4:6])]} {stamp[:4]}" \
        if stamp.isdigit() else ""
    hello = next((r for r in recs if r["event"] == "hello"), {})
    return {"players": players, "order": order, "winner": winner, "final_turn": (game_over or {}).get("turn"),
            "outcome": (summary or {}).get("outcome"), "date": date, "game_version": hello.get("game_version")}


# ------------------------------------------------------------------ drawing helpers

def load_fonts() -> dict[str, str]:
    """Josefin Sans (the game's typeface) if it is in %USERPROFILE%/tools/fonts, else Segoe UI."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    files = [f for f in (home / "tools" / "fonts").rglob("*.ttf") if "josefin" in f.name.lower()]
    statics = [f for f in files if "[wght]" not in f.name]
    found = {}
    # a variable font registers as its default (thin) instance, so prefer cut static weights when present
    for f in (statics or files):
        font_manager.fontManager.addfont(str(f))
        n = f.name.lower()
        if "italic" in n:
            continue
        if "semibold" in n:
            found["bold"] = str(f)
        elif "-regular" in n or "[wght]" in n:
            found.setdefault("regular", str(f))
    family = "Josefin Sans" if found else "Segoe UI"
    plt.rcParams["font.family"] = family
    return {"family": family, **found}


def sky(ax) -> None:
    top, bottom = np.array(matplotlib.colors.to_rgb(SKY_TOP)), np.array(matplotlib.colors.to_rgb(SKY_BOTTOM))
    ramp = np.linspace(0, 1, 256)[:, None]
    img = top * (1 - ramp) + bottom * ramp
    ax.imshow(img[:, None, :].repeat(2, axis=1), extent=(0, 1, 0, 1), aspect="auto", zorder=0, interpolation="bicubic")
    rng = random.Random(7)
    xs = [rng.random() for _ in range(220)]
    ys = [0.25 + 0.75 * rng.random() for _ in range(220)]
    ax.scatter(xs, ys, s=[rng.choice((4, 6, 9, 12)) for _ in range(220)], c="white",
               alpha=[0.35 + 0.5 * rng.random() for _ in range(220)], linewidths=0, zorder=1)


def island(ax, top: float = 0.075) -> None:
    """A low-poly strip along the bottom edge: flat green triangles with a bit of water at the left."""
    rng = random.Random(11)
    n = 26
    xs = np.linspace(-0.02, 1.02, n)
    ys = [top + rng.uniform(-0.028, 0.02) for _ in range(n)]
    polys, colors = [], []
    for i in range(n - 1):
        x0, x1 = xs[i], xs[i + 1]
        mid = (x0 + x1) / 2
        base = -0.01
        polys.append([(x0, base), (x1, base), (x0, ys[i])]); colors.append(rng.choice(GREENS))
        polys.append([(x1, base), (x1, ys[i + 1]), (x0, ys[i])]); colors.append(rng.choice(GREENS))
        polys.append([(x0, ys[i]), (x1, ys[i + 1]), (mid, max(ys[i], ys[i + 1]) + rng.uniform(0.004, 0.018))])
        colors.append(rng.choice(GREENS))
    for i in range(4):   # water at the left corner
        polys.append([(0 + 0.04 * i, -0.01), (0.05 + 0.04 * i, -0.01), (0.02 + 0.04 * i, 0.03 + rng.uniform(0, 0.02))])
        colors.append(rng.choice(WATER))
    ax.add_collection(PolyCollection(polys, facecolors=colors, edgecolors="none", zorder=2))


def panel(ax, x, y, w, h, *, color="white", alpha=0.16, radius=0.012, zorder=2) -> None:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
                                facecolor=color, edgecolor="none", alpha=alpha, zorder=zorder, mutation_aspect=W / H))


def swords(ax, cx, cy, size=0.05) -> None:
    """Crossed swords, the Domination win glyph, as flat polygons."""
    for angle, dx in ((45, -1), (-45, 1)):
        a = np.radians(angle)
        u = np.array([np.cos(a), np.sin(a) * W / H])          # along the blade, aspect corrected
        v = np.array([-np.sin(a), np.cos(a) * W / H])         # across
        c = np.array([cx, cy])
        blade = [c + u * size * 0.05 + v * size * 0.10, c + u * size * 1.0 + v * size * 0.10,
                 c + u * size * 1.18, c + u * size * 1.0 - v * size * 0.10, c + u * size * 0.05 - v * size * 0.10]
        ax.add_patch(Polygon(blade, closed=True, facecolor="#dff3ff", edgecolor="#9fd3ee", linewidth=1.2, zorder=6))
        guard = [c + u * size * 0.05 + v * size * 0.32, c + u * size * 0.05 - v * size * 0.32,
                 c - u * size * 0.06 - v * size * 0.32, c - u * size * 0.06 + v * size * 0.32]
        ax.add_patch(Polygon(guard, closed=True, facecolor="#8b8f99", edgecolor="none", zorder=7))
        grip = [c - u * size * 0.06 + v * size * 0.11, c - u * size * 0.06 - v * size * 0.11,
                c - u * size * 0.55 - v * size * 0.11, c - u * size * 0.55 + v * size * 0.11]
        ax.add_patch(Polygon(grip, closed=True, facecolor="#f2a33a", edgecolor="none", zorder=7))
        pommel = [c - u * size * 0.55 + v * size * 0.18, c - u * size * 0.55 - v * size * 0.18,
                  c - u * size * 0.7 - v * size * 0.12, c - u * size * 0.7 + v * size * 0.12]
        ax.add_patch(Polygon(pommel, closed=True, facecolor="#e2552f", edgecolor="none", zorder=7))


def leader(fig, ax, y, left: str, right: str, *, x0=0.16, x1=0.84, size=30, note: str | None = None) -> None:
    """'Name ............ 4,875' with a dotted fill measured to the text, the way the game's end screen prints it."""
    t1 = ax.text(x0, y, left, color="white", fontsize=size, fontweight="bold", ha="left", va="baseline", zorder=8)
    t2 = ax.text(x1, y, right, color="white", fontsize=size, fontweight="bold", ha="right", va="baseline", zorder=8)
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    b1 = t1.get_window_extent(r).transformed(fig.transFigure.inverted())
    b2 = t2.get_window_extent(r).transformed(fig.transFigure.inverted())
    gap0, gap1 = b1.x1 + 0.012, b2.x0 - 0.012
    if gap1 > gap0:
        ax.add_line(Line2D([gap0, gap1], [y + 0.002, y + 0.002], color="white", linewidth=3.2,
                           linestyle=(0, (0.6, 2.4)), dash_capstyle="round", alpha=0.9, zorder=8))
    if note:
        ax.text(x0, y - 0.017, note, color="white", fontsize=16, alpha=0.85, ha="left", va="baseline", zorder=8)


def chart(fig, rect, title, series, *, colors, captures=None, xmax=None, integer=True) -> None:
    ax = fig.add_axes(rect, facecolor=SURFACE)
    ax.set_title(title, loc="left", fontsize=20, color=TEXT, pad=12, fontweight="bold")
    for name, pts in series.items():
        xs, ys = zip(*sorted(pts.items()))
        ax.plot(xs, ys, color=colors[name], linewidth=3.2, solid_capstyle="round", zorder=3)
        ax.plot(xs[-1], ys[-1], marker="o", markersize=11, color=colors[name], markeredgecolor=SURFACE,
                markeredgewidth=2.2, zorder=4)
    if captures:
        for name, turns in captures.items():
            pts = series[name]
            cx = [t for t in turns if t in pts]
            ax.plot(cx, [pts[t] for t in cx], linestyle="none", marker="^", markersize=10, color=colors[name],
                    markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=5)
    # direct end labels, nudged apart when they would collide
    ends = sorted(((max(pts), pts[max(pts)], name) for name, pts in series.items()), key=lambda e: e[1])
    y0, y1 = ax.get_ylim()
    span = (y1 - y0) or 1
    last_y = None
    for x, y, name in ends:
        ly = y
        if last_y is not None and (ly - last_y) < 0.09 * span:
            ly = last_y + 0.09 * span
        ax.annotate(f"{y:,.0f}" if integer else f"{y:g}", (x, y), xytext=(10, 0), textcoords="offset points",
                    ha="left", va="center", fontsize=17, color=TEXT, fontweight="bold", zorder=6,
                    xycoords=("data", "data"), annotation_clip=False) if ly == y else \
            ax.annotate(f"{y:,.0f}", (x, ly), xytext=(10, 0), textcoords="offset points", ha="left", va="center",
                        fontsize=17, color=TEXT, fontweight="bold", zorder=6, annotation_clip=False)
        last_y = ly
    ax.set_xlim(0, (xmax or max(max(p) for p in series.values())) + 0.3)
    ax.set_ylim(min(0, y0), y1 + 0.08 * span)
    ax.margins(x=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.yaxis.grid(True, color=GRID, linewidth=1)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", colors=TEXT2, labelsize=14, length=0)
    ax.set_xticks(range(0, int(ax.get_xlim()[1]) + 1, 2))
    ax.set_xlabel("turn", fontsize=13, color=TEXT2, labelpad=4)


# ------------------------------------------------------------------ the card

def render(match: dict, out: Path) -> None:
    fonts = load_fonts()
    p1, p2 = (match["players"][pid] for pid in match["order"][:2])
    colors = {p["name"]: SERIES[p["backend"]] for p in (p1, p2)}
    winner = match["players"].get(match["winner"]) if match["winner"] in match["players"] else None
    loser = next((p for p in (p1, p2) if p is not winner), None)

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    bg = fig.add_axes([0, 0, 1, 1])
    bg.set_xlim(0, 1); bg.set_ylim(0, 1); bg.axis("off")
    sky(bg)
    island(bg, top=0.058)

    # header
    bg.text(0.5, 0.965, "THE BATTLE OF POLYTOPIA", ha="center", va="center", fontsize=22, color="white", alpha=0.9,
            zorder=8, fontweight="bold")
    bg.text(0.5, 0.928, f"{p1['name']}  vs  {p2['name']}", ha="center", va="center", fontsize=44, color="white",
            zorder=8, fontweight="bold")
    bg.text(0.5, 0.898, f"AI deathmatch  |  Pass & Play, Domination, tiny map  |  both at medium reasoning  |  {match['date']}",
            ha="center", va="center", fontsize=19, color="white", alpha=0.92, zorder=8)

    # hero: the end screen
    swords(bg, 0.5, 0.835, size=0.05)
    if winner:
        headline = f"{winner['name']} wins on turn {match['final_turn']}"
    elif match["outcome"] == "max_turns":
        headline = f"Undecided after turn {match['final_turn']}"
    else:
        headline = f"Stopped: {match['outcome']}"
    bg.text(0.5, 0.775, headline, ha="center", va="center", fontsize=52, color="white", zorder=8)
    bg.text(0.5, 0.749, "You have defeated all the other tribes and unified the entire Square!" if winner else "",
            ha="center", va="center", fontsize=17, color="white", alpha=0.9, zorder=8)
    y = 0.716
    for p in ([winner, loser] if winner else [p1, p2]):
        if p is None:
            continue
        killed = p["final"].get("killed_turn") or 0
        note = f"Imperius, killed on turn {killed}" if killed else "Imperius"
        leader(fig, bg, y, p["name"], f"{p['final'].get('score', 0):,}", note=note)
        y -= 0.052

    # charts on one cream surface
    px, py, pw, ph = 0.05, 0.215, 0.90, 0.385
    panel(bg, px, py, pw, ph, color=SURFACE, alpha=1.0, radius=0.014, zorder=2)
    # legend row
    lx = px + 0.03
    for p in (p1, p2):
        bg.add_patch(FancyBboxPatch((lx, py + ph - 0.036), 0.016, 0.0128, boxstyle="round,pad=0,rounding_size=0.003",
                                    facecolor=colors[p["name"]], edgecolor="none", zorder=5, mutation_aspect=W / H))
        t = bg.text(lx + 0.024, py + ph - 0.030, p["name"] + ("  (moves first)" if p is p1 else ""), fontsize=18,
                    color=TEXT, va="center", ha="left", zorder=5)
        fig.canvas.draw()
        lx = t.get_window_extent(fig.canvas.get_renderer()).transformed(fig.transFigure.inverted()).x1 + 0.035
    bg.text(px + pw - 0.03, py + ph - 0.030, "values at the start of each turn", fontsize=14, color=TEXT2,
            va="center", ha="right", zorder=5)
    xmax = max(max(p["turns"]) for p in (p1, p2))
    panels = [("Stars in the treasury", "stars", None), ("Income per turn", "income", None),
              ("Score", "score", None), ("Cities  (triangles: villages captured)", "cities", "captures"),
              ("Units alive", "units", None), ]
    cols, rows = 2, 3
    cw, ch = (pw - 0.10) / cols, (ph - 0.075) / rows
    for i, (title, key, extra) in enumerate(panels):
        c, r = i % cols, i // cols
        rect = [px + 0.05 + c * (cw + 0.02) + (0.0 if c == 0 else -0.02), py + ph - 0.075 - (r + 1) * ch + 0.035,
                cw - 0.03, ch - 0.055]
        series = {p["name"]: {t: v[key] for t, v in p["turns"].items()} for p in (p1, p2)}
        captures = {p["name"]: p["captures"] for p in (p1, p2)} if extra == "captures" else None
        chart(fig, rect, title, series, colors=colors, captures=captures, xmax=xmax)
    # the sixth cell: how the match was run
    via = {"claude": "Claude via Claude Code", "codex": "Codex via codex exec", "grok": "Grok via Grok Build"}
    routes = ", ".join(via[p["backend"]] for p in (p1, p2))
    bg.text(px + 0.05 + 1 * (cw + 0.02) - 0.02, py + 0.04,
            "Same rules, observation, plan schema and budgets for both seats\n"
            "(3 model calls and 60 actions per turn), no tools, same tribe.\n"
            f"{routes}; each seat sees only\n"
            "its own fog of war. Log and transcript: polytopia-claude repo.",
            fontsize=14.5, color=TEXT2, va="bottom", ha="left", zorder=5, linespacing=1.55)

    # stat tiles
    tiles = [
        ("Model calls", [str(p["seat"].get("calls", "?")) for p in (p1, p2)]),
        ("Median call", [f"{p['median_latency']:.0f} s" if p["median_latency"] else "?" for p in (p1, p2)]),
        ("Units lost", [str(p2["kills"]), str(p1["kills"])]),
        ("Villages captured", [str(len(p["captures"])) for p in (p1, p2)]),
        ("Cost", [("subscription" if p["seat"].get("cost_usd") is None else f"${p['seat']['cost_usd']:.2f}") for p in (p1, p2)]),
    ]
    tx, ty, tw, th, gap = 0.05, 0.105, (0.90 - 4 * 0.014) / 5, 0.09, 0.014
    for i, (label, values) in enumerate(tiles):
        x = tx + i * (tw + gap)
        panel(bg, x, ty, tw, th, alpha=0.18, radius=0.010, zorder=3)
        bg.text(x + tw / 2, ty + th - 0.02, label, ha="center", va="center", fontsize=16, color="white", alpha=0.9, zorder=8)
        for j, (p, v) in enumerate(zip((p1, p2), values)):
            yy = ty + th - 0.046 - j * 0.026
            bg.add_patch(FancyBboxPatch((x + 0.016, yy - 0.005), 0.012, 0.0096, boxstyle="round,pad=0,rounding_size=0.002",
                                        facecolor=colors[p["name"]], edgecolor="white", linewidth=1, zorder=8, mutation_aspect=W / H))
            bg.text(x + 0.036, yy, p["name"].split(" ")[0], ha="left", va="center", fontsize=15, color="white", zorder=8)
            bg.text(x + tw - 0.016, yy, v, ha="right", va="center", fontsize=19, color="white", fontweight="bold", zorder=8)

    bg.text(0.5, 0.083, "Two AI agents, one Polytopia game.  Recorded 7 Sep 2026 on the Steam build of The Battle of Polytopia.",
            ha="center", va="center", fontsize=14, color="white", alpha=0.95, zorder=8)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=100)
    plt.close(fig)
    print(f"wrote {out} ({W}x{H}, font {fonts['family']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="deathmatch JSONL log")
    ap.add_argument("--out", default=None, help="output PNG (default: <log stem>-card.png next to the log)")
    args = ap.parse_args()
    log = Path(args.log)
    out = Path(args.out) if args.out else log.with_name(log.stem + "-card.png")
    render(load_match(log), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
