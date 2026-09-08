"""Turn a bridge `state` message into a compact text observation for the model.

Layout (all coordinates are (x, y), x to the right, y down):

    header      turn / mode / difficulty / economy / techs
    objective   (Domination) where the enemy capital is, or that it is still unexplored
    players     opponents, relations
    map         ASCII grid over the explored bounding box, 3 chars per tile:
                terrain, feature (city/village/ruin/resource/improvement), unit
    cities      one line per city: level, population, unit support, city-tile occupant, worked resources
    units       ours and visible enemies
    actions     numbered legal actions; moves (and monument placements) are grouped per unit/type

`render()` returns the text and the index -> action list, so the agent picks by number.
`summarize_change()` describes what actually happened between two states (for the spectator console
and for the planner's "this turn so far" log).
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
    "Battleship": "L", "Cloak": "Q", "Dagger": "Y", "Polytaur": "P", "Tridention": "N", "Raft": "B",
}

LEGEND = (
    "terrain . field ^ mountain T forest ~ water = ocean # ice ; wetland : mangrove ? unexplored | "
    "feature C your city E enemy city * enemy CAPITAL v village r ruin + improvement, resources g game c crop "
    "f fish w whale m metal u fruit s spores x starfish | unit: your units UPPERCASE, enemies lowercase "
    "(W warrior R rider A archer D defender S swordsman K knight C catapult G giant M mind bender "
    "O scout B boat/raft H ship L battleship)"
)


def xy(p) -> str:
    return f"({p[0]},{p[1]})"


_xy = xy   # backwards-compatible name


def dist(a, b) -> int:
    """Chebyshev distance in tiles (straight line; terrain, roads and enemies change the real travel time)."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def enemy_capital(st: dict[str, Any]) -> dict[str, Any] | None:
    my_id = st["me"]["id"]
    for c in st["cities"]:
        if c["owner"] != my_id and c["owner"] != 0 and c.get("is_capital"):
            return c
    return None


def _map_lines(st: dict[str, Any], tiles: dict, units_at: dict) -> list[str]:
    my_id = st["me"]["id"]
    cities_at = {(c["x"], c["y"]): c for c in st["cities"]}
    xs = [x for x, _ in tiles]
    ys = [y for _, y in tiles]
    if not xs:
        return ["MAP: nothing explored"]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    out = [f"MAP (explored region x {x0}-{x1}, y {y0}-{y1}; each cell = terrain feature unit):",
           "    " + " ".join(f"{x:2d}" for x in range(x0, x1 + 1))]
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
                c = cities_at.get((x, y))
                if t["owner"] == my_id:
                    feature = "C"
                elif c is not None and c.get("is_capital"):
                    feature = "*"
                else:
                    feature = "E"
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
    return out


def render_map(msg: dict[str, Any]) -> str:
    st = msg["state"]
    tiles = {(t["x"], t["y"]): t for t in st["tiles"]}
    units_at = {(u["x"], u["y"]): u for u in st["units"]}
    return "\n".join(_map_lines(st, tiles, units_at))


def _unit_status(u: dict[str, Any]) -> list[str]:
    status = []
    if "can_move" in u or "can_attack" in u:
        cm, ca = u.get("can_move"), u.get("can_attack")
        if cm and ca:
            status.append("ready")
        elif cm:
            status.append("can move")
        elif ca:
            status.append("can attack")
        else:
            status.append("done")
    else:
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
    return status


def _list_xy(points, cap: int = 24) -> str:
    pts = sorted(points)
    s = " ".join(xy(p) for p in pts[:cap])
    if len(pts) > cap:
        s += f" (+{len(pts) - cap} more)"
    return s


def describe_matchup(st: dict[str, Any]) -> str:
    """'Domination vs 1 Normal bot(s)' for a single-player game; 'Domination | 2 players' when other
    humans (or another AI) hold seats, with the bot count appended if bots are mixed in."""
    settings = st["settings"]
    my_id = st["me"]["id"]
    players = st.get("players") or []
    opponents = [p for p in players if p["id"] != my_id]
    bots = [p for p in opponents if p.get("is_bot")]
    if opponents and len(bots) == len(opponents):
        return f"{settings['game_mode']} vs {settings['opponents']} {settings['difficulty']} bot(s)"
    s = f"{settings['game_mode']} | {len(players)} players"
    if bots:
        s += f" ({len(bots)} {settings['difficulty']} bot(s))"
    return s


def render(msg: dict[str, Any], notes: str | None = None, *, legend: bool = True) -> tuple[str, list[dict[str, Any]]]:
    st = msg["state"]
    legal = msg["legal_actions"]
    me = st["me"]
    settings = st["settings"]
    my_id = me["id"]
    domination = str(settings.get("game_mode", "")).lower() == "domination"

    tiles = {(t["x"], t["y"]): t for t in st["tiles"]}
    units_at = {(u["x"], u["y"]): u for u in st["units"]}
    out: list[str] = []

    # ---------------------------------------------------------------- header
    limit = settings.get("turn_limit") or 0
    turn = f"{st['turn']}/{limit}" if limit else str(st["turn"])
    out.append(f"TURN {turn} | {describe_matchup(st)} | map {settings['map_width']}x{settings['map_height']}")
    out.append(
        f"YOU: {me['tribe']} (player {my_id}) | stars {me['stars']} spendable now | income {me['income']}/turn | score {me['score']} | "
        f"techs: {', '.join(me['techs']) or 'none'}"
    )

    # ---------------------------------------------------------------- objective
    cap = enemy_capital(st) if domination else None
    enemy_units = [u for u in st["units"] if u["owner"] != my_id]
    theirs_all = [c for c in st["cities"] if c["owner"] != my_id and c["owner"] != 0]
    if domination:
        reported = sum(p.get("cities", 0) for p in st["players"] if p["id"] != my_id and p.get("alive", True))
        if cap:
            garrison = units_at.get((cap["x"], cap["y"]))
            g = (f"garrison {garrison['type']}#{garrison['id']} hp {garrison['hp']:g}/{garrison['max_hp']:g}"
                 if garrison else "no unit inside")
            out.append(
                f"OBJECTIVE: Domination - eliminate the opponent by capturing ALL their cities "
                f"({reported} reported, {len(theirs_all)} located). "
                f"Enemy capital {cap['name']} at {xy((cap['x'], cap['y']))}, level {cap['level']}"
                f"{', walls' if cap.get('walls') else ''}, {g}."
            )
        elif theirs_all:
            rest = ", ".join(f"{c['name']} {xy((c['x'], c['y']))} level {c['level']}" for c in theirs_all)
            out.append(
                f"OBJECTIVE: Domination - eliminate the opponent by capturing ALL their cities "
                f"({reported} reported, {len(theirs_all)} located). "
                f"No enemy capital is visible (already taken, or unexplored). Remaining known enemy cities: {rest}."
            )
        else:
            seen = ", ".join(f"{u['type']} at {xy((u['x'], u['y']))}" for u in enemy_units[:6])
            out.append(
                f"OBJECTIVE: Domination - eliminate the opponent by capturing ALL their cities ({reported} reported, none located). "
                "Enemy capital NOT FOUND YET: scout toward unexplored tiles"
                + (f"; enemy units visible: {seen}" if seen else "") + "."
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
        out.append(f"!! PENDING {trig['type']} at {xy(trig['at'])}: you must answer it now (see actions).")

    # ---------------------------------------------------------------- map
    out.extend(_map_lines(st, tiles, units_at))
    if legend:
        out.append("legend: " + LEGEND)
    roads = [k for k, t in tiles.items() if t.get("road")]
    if roads:
        out.append("ROADS: " + _list_xy(roads))
    enemy_land = [k for k, t in tiles.items()
                  if t.get("owner") not in (0, my_id, None) and t.get("improvement") != "City"]
    if enemy_land:
        out.append("ENEMY TERRITORY (visible tiles): " + _list_xy(enemy_land, 20))

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
            supported = sum(1 for u in st["units"] if u["owner"] == my_id and u.get("home") == [c["x"], c["y"]])
            occ = units_at.get((c["x"], c["y"]))
            occ_s = f"{occ['type']}#{occ['id']}" if occ else "empty"
            worked = []
            for (x, y), t in sorted(tiles.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                if t.get("city") == [c["x"], c["y"]] and (x, y) != (c["x"], c["y"]):
                    if not t.get("resource") and not t.get("improvement"):
                        continue
                    desc = t["terrain"].lower()
                    if t.get("resource"):
                        desc += " " + t["resource"].lower()
                    if t.get("improvement"):
                        desc += " " + t["improvement"].upper()
                    worked.append(f"{xy((x, y))} {desc}")
            out.append(
                f"  {c['name']} {xy((c['x'], c['y']))} level {c['level']}, population {c['population']}, "
                f"needs {c['population_to_level']} more pop to level up, supports {supported}/{c['level'] + 1} units, city tile {occ_s}"
                f"{' [' + ', '.join(flags) + ']' if flags else ''}"
            )
            if worked:
                out.append("    resources/improvements: " + "; ".join(worked))
    if theirs:
        out.append("ENEMY CITIES: " + "; ".join(
            f"{c['name']} {xy((c['x'], c['y']))} player {c['owner']} level {c['level']}"
            f"{' CAPITAL' if c.get('is_capital') else ''}{' walls' if c['walls'] else ''}" for c in theirs
        ))
    villages = [k for k, t in tiles.items() if t.get("village")]
    ruins = [k for k, t in tiles.items() if t.get("improvement") == "Ruin"]
    if villages:
        out.append("VILLAGES (a unit that starts its turn on one can capture it): " + " ".join(xy(v) for v in sorted(villages)))
    if ruins:
        out.append("RUINS (examine with a unit): " + " ".join(xy(r) for r in sorted(ruins)))

    # ---------------------------------------------------------------- units
    own = [u for u in st["units"] if u["owner"] == my_id]
    if own:
        out.append("YOUR UNITS:")
        for u in own:
            status = _unit_status(u)
            extra = ""
            if u.get("abilities"):
                extra += " " + "/".join(a.lower() for a in u["abilities"])
            if u.get("kills"):
                extra += f" kills {u['kills']}"
            if cap:
                extra += f" straight-line {dist((u['x'], u['y']), (cap['x'], cap['y']))} to capital"
            out.append(
                f"  #{u['id']} {u['type']} at {xy((u['x'], u['y']))} hp {u['hp']:g}/{u['max_hp']:g} "
                f"atk {u['attack']:g} def-now {u['defence']:g} move {u['movement']} range {u['range']} [{', '.join(status)}]{extra}"
            )
    if enemy_units:
        out.append("ENEMY UNITS: " + "; ".join(
            f"#{u['id']} {u['type']} p{u['owner']} at {xy((u['x'], u['y']))} hp {u['hp']:g}/{u['max_hp']:g} "
            f"atk {u['attack']:g} def-now {u['defence']:g} move {u['movement']} range {u['range']}"
            + (" " + "/".join(a.lower() for a in u["abilities"]) if u.get("abilities") else "")
            for u in enemy_units
        ))

    if notes:
        out.append("YOUR NOTES FROM EARLIER TURNS:\n" + notes.strip())

    # ---------------------------------------------------------------- actions
    out.append("LEGAL ACTIONS (reply with the number):")
    moves: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    monuments: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    lines: list[str] = []
    for i, a in enumerate(legal):
        k = a["kind"]
        if k == "move":
            moves[a["unit_id"]].append((i, a))
            continue
        if k == "build" and "monument" in str(a.get("improvement", "")).lower():
            monuments[str(a["improvement"])].append((i, a))
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
            tgt = f"{a.get('target_type', 'unit')}#{a.get('target_unit_id', '?')} at {xy(a['target'])}"
            eff = f"deals {max(0, a['damage']):g}, takes {max(0, a['retaliation']):g} back" if "damage" in a else ""
            if a.get("kills"):
                eff += " -> KILLS it"
            lines.append(f"[{i}] attack with #{a['unit_id']} -> {tgt} (target hp {a.get('target_hp', 0):g}): {eff}")
        elif k == "train":
            lines.append(
                f"[{i}] train {a['unit_type']} at {xy(a['at'])} ({a.get('cost', '?')} stars: hp {a.get('hp')} atk {a.get('attack')} "
                f"def {a.get('defence')} move {a.get('movement')} range {a.get('range')})"
            )
        elif k == "build":
            gains = []
            if a.get("population"):
                gains.append(f"+{a['population']} pop")
            if a.get("stars"):
                gains.append(f"+{a['stars']} stars")
            lines.append(f"[{i}] build {a['improvement']} at {xy(a['at'])} ({a.get('cost', '?')} stars{', ' + ', '.join(gains) if gains else ''})")
        elif k == "city_reward":
            lines.append(f"[{i}] city reward: {a['reward']} for city at {xy(a['at'])}")
        elif k == "capture":
            lines.append(f"[{i}] capture village/city at {xy(a['at'])} with #{a['unit_id']}")
        elif k == "upgrade":
            lines.append(f"[{i}] upgrade unit at {xy(a['at'])} to {a['unit_type']}")
        elif k == "peace_request_response":
            lines.append(f"[{i}] {'accept' if a['accept'] else 'decline'} peace with player {a['opponent']}")
        elif k in ("peace_treaty", "establish_embassy", "destroy_embassy", "break_peace"):
            lines.append(f"[{i}] {k.replace('_', ' ')} with player {a['opponent']} at {xy(a['at'])}")
        elif "at" in a:
            lines.append(f"[{i}] {k.replace('_', ' ')} at {xy(a['at'])}")
        else:
            lines.append(f"[{i}] {k.replace('_', ' ')} {a}")
    for unit_id, entries in moves.items():
        dests = " ".join(f"{xy(a['to'])}[{i}]" for i, a in entries)
        lines.append(f"move #{unit_id} to: {dests}")
    for name, entries in monuments.items():
        a0 = entries[0][1]
        gains = f"+{a0['population']} pop" if a0.get("population") else "score only"
        spots = " ".join(f"{xy(a['at'])}[{i}]" for i, a in entries)
        lines.append(f"build {name} ({a0.get('cost', 0)} stars, {gains}; ONE placement, pick one tile) at: {spots}")
    out.extend(lines)
    return "\n".join(out), legal


# ---------------------------------------------------------------- what actually happened

def summarize_change(before: dict[str, Any], after: dict[str, Any], *, enemy_turn: bool = False) -> str:
    """Compact description of the differences between two states (stars, units, cities, techs)."""
    my_id = after["me"]["id"]
    bits: list[str] = []
    if before["me"]["stars"] != after["me"]["stars"]:
        bits.append(f"stars {before['me']['stars']}->{after['me']['stars']}")
    new_techs = [t for t in after["me"].get("techs", []) if t not in before["me"].get("techs", [])]
    if new_techs:
        bits.append("learned " + ", ".join(new_techs))

    b_units = {u["id"]: u for u in before["units"]}
    a_units = {u["id"]: u for u in after["units"]}
    for uid, u in b_units.items():
        mine = u["owner"] == my_id
        tag = f"{u['type']}#{uid}" if mine else f"enemy {u['type']}#{uid}"
        v = a_units.get(uid)
        if v is None:
            bits.append(f"lost {tag}" if mine else f"{tag} gone (killed or out of sight)")
            continue
        if v["owner"] != u["owner"]:
            bits.append(f"{tag} changed owner to player {v['owner']}")
        if v["hp"] != u["hp"]:
            bits.append(f"{tag} hp {u['hp']:g}->{v['hp']:g}")
        if (v["x"], v["y"]) != (u["x"], u["y"]):
            bits.append(f"{tag} -> {xy((v['x'], v['y']))}")
    for uid, v in a_units.items():
        if uid not in b_units:
            tag = f"{v['type']}#{uid}" if v["owner"] == my_id else f"enemy {v['type']}#{uid}"
            bits.append(f"new {tag} at {xy((v['x'], v['y']))}")

    b_cities = {(c["x"], c["y"]): c for c in before["cities"]}
    a_cities = {(c["x"], c["y"]): c for c in after["cities"]}
    for k, c in a_cities.items():
        o = b_cities.get(k)
        if o is None:
            who = "yours" if c["owner"] == my_id else f"player {c['owner']}"
            bits.append(f"city {c['name']} {xy(k)} now seen/owned ({who})")
            continue
        if o["owner"] != c["owner"]:
            who = "YOURS" if c["owner"] == my_id else f"player {c['owner']}"
            bits.append(f"city {c['name']} {xy(k)} captured -> {who}")
        if o["level"] != c["level"]:
            bits.append(f"{c['name']} level {o['level']}->{c['level']}")
        elif o.get("population") != c.get("population") and c["owner"] == my_id:
            bits.append(f"{c['name']} pop {o.get('population')}->{c.get('population')}")
    if enemy_turn:
        return "; ".join(bits) if bits else "nothing visible changed"
    return "; ".join(bits)


def estimate_tokens(text: str) -> int:
    """Rough size check (~4 chars/token). Use messages.count_tokens for real numbers."""
    return len(text) // 4
