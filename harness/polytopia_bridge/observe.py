"""Turn a bridge `state` message into a compact text observation for the model.

Layout (all coordinates are (x, y), x to the right, y down):

    header      turn / mode / difficulty / economy / techs
    players     opponents, relations
    map         ASCII grid over the explored bounding box, 3 chars per tile:
                terrain, feature (city/village/ruin/resource/improvement), unit
    cities      one line per city with its worked tiles
    units       ours and visible enemies
    actions     numbered legal actions; moves are grouped per unit

`render()` returns the text and the index -> action list, so the agent picks by number.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

TERRAIN = {
    "Field": ".", "Forest": "T", "Mountain": "^", "Water": "~", "Ocean": "=",
    "Ice": "#", "Wetland": ";", "Mangrove": ":", "None": " ",
}
RESOURCE = {
    "Game": "g", "Crop": "c", "Fish": "f", "Whale": "w", "Metal": "m", "Fruit": "u",
    "Spores": "s", "Starfish": "x", "AquaCrop": "q",
}
UNIT_LETTERS = {
    "Warrior": "W", "Rider": "R", "Archer": "A", "Defender": "D", "Swordsman": "S", "Knight": "K",
    "Catapult": "C", "Giant": "G", "MindBender": "M", "Scout": "O", "Boat": "B", "Ship": "H",
    "Battleship": "L", "Cloak": "Q", "Dagger": "Y", "Polytaur": "P", "Tridention": "N",
}

LEGEND = (
    "terrain . field ^ mountain T forest ~ water = ocean # ice ; wetland : mangrove ? unexplored | "
    "feature C your city c enemy city v village r ruin + improvement, resources g game c crop f fish "
    "w whale m metal u fruit s spores x starfish | unit: your units UPPERCASE, enemies lowercase "
    "(W warrior R rider A archer D defender S swordsman K knight C catapult G giant M mind bender "
    "O scout B boat H ship L battleship)"
)


def _xy(p) -> str:
    return f"({p[0]},{p[1]})"


def render(msg: dict[str, Any], notes: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    st = msg["state"]
    legal = msg["legal_actions"]
    me = st["me"]
    settings = st["settings"]
    my_id = me["id"]

    tiles = {(t["x"], t["y"]): t for t in st["tiles"]}
    units_at = {(u["x"], u["y"]): u for u in st["units"]}
    cities_at = {(c["x"], c["y"]): c for c in st["cities"]}
    out: list[str] = []

    # ---------------------------------------------------------------- header
    limit = settings.get("turn_limit") or 0
    turn = f"{st['turn']}/{limit}" if limit else str(st["turn"])
    out.append(
        f"TURN {turn} | {settings['game_mode']} vs {settings['opponents']} {settings['difficulty']} bot(s) | "
        f"map {settings['map_width']}x{settings['map_height']}"
    )
    out.append(
        f"YOU: {me['tribe']} (player {my_id}) | stars {me['stars']} (+{me['income']}/turn) | score {me['score']} | "
        f"techs: {', '.join(me['techs']) or 'none'}"
    )

    # ---------------------------------------------------------------- players
    others = []
    for p in st["players"]:
        if p["id"] == my_id:
            continue
        bits = [f"{p['tribe']} (player {p['id']}{', bot' if p['is_bot'] else ''})", f"score {p['score']}", f"{p['cities']} cities"]
        if not p["alive"]:
            bits.append("ELIMINATED")
        elif not p["known"]:
            bits.append("not met")
        elif p.get("relation"):
            bits.append(p["relation"].lower())
        others.append(" ".join(bits))
    if others:
        out.append("OPPONENTS: " + "; ".join(others))

    if st.get("pending_trigger"):
        trig = st["pending_trigger"]
        out.append(f"!! PENDING {trig['type']} at {_xy(trig['at'])}: you must answer it now (see actions).")

    # ---------------------------------------------------------------- map
    xs = [x for x, _ in tiles]
    ys = [y for _, y in tiles]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    out.append(f"MAP (explored region x {x0}-{x1}, y {y0}-{y1}; each cell = terrain feature unit):")
    out.append("    " + " ".join(f"{x:2d}" for x in range(x0, x1 + 1)))
    for y in range(y0, y1 + 1):
        row = []
        for x in range(x0, x1 + 1):
            t = tiles.get((x, y))
            if t is None:
                row.append(" ? ")
                continue
            terrain = TERRAIN.get(t["terrain"], "?")
            feature = " "
            if t.get("village"):
                feature = "v"
            elif t.get("improvement") == "City":
                feature = "C" if t["owner"] == my_id else "c"
            elif t.get("improvement") == "Ruin":
                feature = "r"
            elif t.get("improvement"):
                feature = "+"
            elif t.get("resource"):
                feature = RESOURCE.get(t["resource"], "?")
            u = units_at.get((x, y))
            unit = " "
            if u:
                letter = UNIT_LETTERS.get(u["type"], u["type"][0])
                unit = letter if u["owner"] == my_id else letter.lower()
            row.append(terrain + feature + unit)
        out.append(f"{y:2d}  " + "".join(row))
    out.append("legend: " + LEGEND)

    # ---------------------------------------------------------------- cities
    mine = [c for c in st["cities"] if c["owner"] == my_id]
    theirs = [c for c in st["cities"] if c["owner"] != my_id]
    if mine:
        out.append("YOUR CITIES:")
        for c in mine:
            flags = []
            if c["is_capital"]:
                flags.append("capital")
            if c["walls"]:
                flags.append("walls")
            if c["rewards"]:
                flags.append("rewards " + ",".join(c["rewards"]))
            worked = []
            for (x, y), t in sorted(tiles.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                if t.get("city") == [c["x"], c["y"]] and (x, y) != (c["x"], c["y"]):
                    desc = t["terrain"].lower()
                    if t.get("resource"):
                        desc += " " + t["resource"].lower()
                    if t.get("improvement"):
                        desc += " " + t["improvement"].upper()
                    worked.append(f"{_xy((x, y))} {desc}")
            out.append(
                f"  {c['name']} {_xy((c['x'], c['y']))} level {c['level']}, pop {c['population']}/{c['population_to_level']} "
                f"to next level, +{c['production']}/turn{' [' + ', '.join(flags) + ']' if flags else ''}"
            )
            if worked:
                out.append("    territory: " + "; ".join(worked))
    if theirs:
        out.append("ENEMY CITIES: " + "; ".join(
            f"{c['name']} {_xy((c['x'], c['y']))} player {c['owner']} level {c['level']}{' walls' if c['walls'] else ''}" for c in theirs
        ))
    villages = [k for k, t in tiles.items() if t.get("village")]
    ruins = [k for k, t in tiles.items() if t.get("improvement") == "Ruin"]
    if villages:
        out.append("VILLAGES (capture by ending a unit's turn on them): " + " ".join(_xy(v) for v in sorted(villages)))
    if ruins:
        out.append("RUINS (examine with a unit): " + " ".join(_xy(r) for r in sorted(ruins)))

    # ---------------------------------------------------------------- units
    own = [u for u in st["units"] if u["owner"] == my_id]
    enemies = [u for u in st["units"] if u["owner"] != my_id]
    if own:
        out.append("YOUR UNITS:")
        for u in own:
            status = []
            if u.get("moved"):
                status.append("moved")
            if u.get("attacked"):
                status.append("attacked")
            if not u.get("moved") and not u.get("attacked"):
                status.append("ready")
            if u.get("veteran"):
                status.append("veteran")
            if u.get("effects"):
                status += [e.lower() for e in u["effects"]]
            out.append(
                f"  #{u['id']} {u['type']} at {_xy((u['x'], u['y']))} hp {u['hp']:g}/{u['max_hp']:g} "
                f"atk {u['attack']:g} def {u['defence']:g} move {u['movement']} range {u['range']} [{', '.join(status)}]"
            )
    if enemies:
        out.append("ENEMY UNITS: " + "; ".join(
            f"#{u['id']} {u['type']} p{u['owner']} at {_xy((u['x'], u['y']))} hp {u['hp']:g}/{u['max_hp']:g} atk {u['attack']:g} def {u['defence']:g}"
            for u in enemies
        ))

    if notes:
        out.append("YOUR NOTES FROM EARLIER TURNS:\n" + notes.strip())

    # ---------------------------------------------------------------- actions
    out.append("LEGAL ACTIONS (reply with the number):")
    moves: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    lines: list[str] = []
    for i, a in enumerate(legal):
        k = a["kind"]
        if k == "move":
            moves[a["unit_id"]].append((i, a))
            continue
        if k == "end_turn":
            lines.append(f"[{i}] end turn")
        elif k == "research":
            unlocks = [x for x in a.get("unlocks_units", []) + a.get("unlocks_improvements", [])]
            nxt = a.get("unlocks_techs", [])
            extra = []
            if unlocks:
                extra.append("unlocks " + ", ".join(unlocks))
            if nxt:
                extra.append("leads to " + ", ".join(nxt))
            lines.append(f"[{i}] research {a['tech']} ({a['cost']} stars){': ' + '; '.join(extra) if extra else ''}")
        elif k == "attack":
            tgt = f"{a.get('target_type', 'unit')}#{a.get('target_unit_id', '?')} at {_xy(a['target'])}"
            eff = f"deals {a['damage']:g}, takes {a['retaliation']:g} back" if "damage" in a else ""
            if a.get("kills"):
                eff += " -> KILLS it"
            lines.append(f"[{i}] attack with #{a['unit_id']} -> {tgt} (target hp {a.get('target_hp', 0):g}): {eff}")
        elif k == "train":
            lines.append(
                f"[{i}] train {a['unit_type']} at {_xy(a['at'])} ({a.get('cost', '?')} stars: hp {a.get('hp')} atk {a.get('attack')} "
                f"def {a.get('defence')} move {a.get('movement')} range {a.get('range')})"
            )
        elif k == "build":
            gains = []
            if a.get("population"):
                gains.append(f"+{a['population']} pop")
            if a.get("stars"):
                gains.append(f"+{a['stars']} stars")
            lines.append(f"[{i}] build {a['improvement']} at {_xy(a['at'])} ({a.get('cost', '?')} stars{', ' + ', '.join(gains) if gains else ''})")
        elif k == "city_reward":
            lines.append(f"[{i}] city reward: {a['reward']} for city at {_xy(a['at'])}")
        elif k == "capture":
            lines.append(f"[{i}] capture village/city at {_xy(a['at'])} with #{a['unit_id']}")
        elif k == "upgrade":
            lines.append(f"[{i}] upgrade unit at {_xy(a['at'])} to {a['unit_type']}")
        elif k == "peace_request_response":
            lines.append(f"[{i}] {'accept' if a['accept'] else 'decline'} peace with player {a['opponent']}")
        elif k in ("peace_treaty", "establish_embassy", "destroy_embassy", "break_peace"):
            lines.append(f"[{i}] {k.replace('_', ' ')} with player {a['opponent']} at {_xy(a['at'])}")
        elif "at" in a:
            lines.append(f"[{i}] {k.replace('_', ' ')} at {_xy(a['at'])}")
        else:
            lines.append(f"[{i}] {k.replace('_', ' ')} {a}")
    for unit_id, entries in moves.items():
        dests = " ".join(f"{_xy(a['to'])}[{i}]" for i, a in entries)
        lines.append(f"move #{unit_id} to: {dests}")
    out.extend(lines)
    return "\n".join(out), legal


def estimate_tokens(text: str) -> int:
    """Rough size check (~4 chars/token). Use messages.count_tokens for real numbers."""
    return len(text) // 4
