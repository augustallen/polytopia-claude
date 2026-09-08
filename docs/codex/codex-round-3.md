Read-only review completed; no files modified. The largest gains would come from a stronger opening, spending toward immediate rewards, and planning explicitly around the snapshot action list.

1. **Make the Imperius opening precise, and stop automatically choosing Explorer.** In [strategy_domination.md](C:/Users/augus/polytopia-claude/harness/polytopia_bridge/strategy_domination.md), replace the opening guidance with:

   > “Imperius starts with Organization. On the first playable turn, normally harvest two fruit for 4 stars to reach capital level 2, take Workshop, and move the starting Warrior toward a nearby village or useful scouting frontier. Buy a second Warrior when it accelerates a separate village capture or answers an immediate threat; do not train automatically just because a support slot is available.”

   The runner currently selects Explorer whenever the capital is unknown and the turn is ≤6—including the opening capital upgrade. For this setup, delete that priority override in `choose_reward()` and retain `REWARD_PRIORITY`, which already prefers Workshop. An Explorer can be valuable, but “capital unknown” alone does not justify sacrificing opening income.

2. **Replace the automatic Riding purchase and turn-12 technology threshold with concrete purchase conditions.**

   > “Buy Riding when you can fund a useful Rider soon without delaying an immediate village capture or valuable city reward. Warriors explore adequately through fresh fog; Riders excel at crossing revealed ground, reinforcing, and attacking then escaping. Research Roads when specific road placements shorten reinforcement or attack routes enough to justify the research and construction costs. Add Hunting → Archery when ranged support solves a defended-city fight. Pursue Smithery when existing prerequisites make Swordsmen an affordable answer; do not wait for an arbitrary turn number. Knights are a situational answer to exposed chains of weak units, not a default tiny-map purchase.”

   Replace “train the cheapest useful unit each turn” with:

   > “Build the unit that supplies the missing role: Warriors for inexpensive capture and occupation, Riders for mobility and repeated attacks, Archers for supported ranged damage, and Giants or stronger units when basic attacks cannot break the defence. Stop recruiting units that cannot reach the remaining fight before it ends.”

3. **Target the easiest useful conquest, and give expansion a stopping condition.**

   “Their CAPITAL is the first target” can send the army past an exposed city into the strongest defence. “Never detour more than 1–2 tiles” also ignores terrain and capture timing. Replace those sentences with:

   > “Capture the enemy city you can take and hold soonest when doing so improves the route to elimination. Prefer the capital when access and survival are comparable; do not bypass an easy forward city solely to attack the capital. Early, claim nearby villages that provide income, recruitment positions, or deny the opponent expansion. Once the current army can finish the remaining cities, stop sending units on village detours and stop buying growth that will not help before victory.”

   Replace the capital-garrison rule with:

   > “Keep the capital empty when no enemy can threaten it before you can respond, preserving its recruitment tile. Defend according to approaching attackers and reinforcement time; one Warrior is not a guarantee.”

4. **Make siege advice describe a survivable occupation, including action-order consequences.**

   Replace the fighting/siege guidance with:

   > “Plan the kill and the occupation together. Use ranged damage first when it reduces retaliation, then choose the melee finisher whose remaining HP and position best survive the enemy reply. A legal melee kill normally advances the attacker onto the target tile; a ranged kill leaves it empty. An attack or move onto the emptied city may require a fresh action list. A besieging unit does not receive the enemy city’s Fortify or wall bonus. Remove nearby counterattackers and protect reinforcement routes before committing. After a Rider attack, use Escape when it preserves the unit or frees an attack lane, but do not abandon a city you intend to capture next turn.”

   Add:

   > “Prefer exchanges that secure a city or remove a dangerous attacker over a simple damage-dealt versus damage-taken comparison. Attack previews describe the current state; earlier hits change subsequent damage and retaliation.”

   These occupation and retaliation distinctions are documented in the [combat rules](https://polytopia.fandom.com/wiki/Combat).

5. **Remove the monument ban; distinguish cheap population from useful population.**

   “Never build … monuments” is strategically wrong: available monuments cost **0 stars and provide 3 population**. They can directly produce Resources or a Giant. [Population reference](https://polytopia.fandom.com/wiki/Population)

   Replace the prohibition and cheap-growth guidance with:

   > “Do not pursue score-only rewards or expensive temples. Use available free monuments when their population accelerates Resources, support capacity, or a Giant; place them without sacrificing a more valuable resource or building site. Buy population toward a named level-up and reward, not merely because a harvest is cheap. Reserve the stars needed for this turn’s decisive recruitment, research, or roads. Do not buy otherwise unnecessary technologies just to unlock a monument.”

   Replace “City rewards … are answered automatically … so do not plan for them” with:

   > “The runner selects city rewards automatically; do not include reward indices, but account for their stars, population, support capacity, and Giant placement when ordering actions.”

6. **Correct the remaining mechanics text in [rules.md](C:/Users/augus/polytopia-claude/harness/polytopia_bridge/rules.md).**

   The blanket claim that ranged attacks at distance 2+ take no retaliation is wrong. Replace it, and the strategy’s “no retaliation” claim, with:

   > “Ranged attacks avoid retaliation when the defender cannot retaliate at that distance; distance 2 alone is not sufficient. Use the displayed retaliation preview.”

   Replace “Forests and mountains stop movement … without the matching tech” with:

   > “For ordinary land units, entering forest normally ends movement; Hunting does not remove this penalty. Mountains require Climbing and normally end movement even after Climbing. Connected roads can overcome forest movement penalties; enemy zones of control also restrict movement. The listed destinations are authoritative.”

   See [combat](https://polytopia.fandom.com/wiki/Combat) and [movement](https://polytopia.fandom.com/wiki/Movement).

   The economy/naval wording also contains pre-update material. Replace the affected sentences with:

   > “Use the reported income and legal improvement rewards for economy calculations. Markets generate stars rather than population; temples do not gain population from adjacent basic improvements. Ports provide population and naval access, not direct star income. Land units embark as Rafts through ports, with naval upgrades governed by the available technologies and actions.”

   Custom Houses and the Boat/Ship/Battleship description predate the [naval rework](https://polytopia.io/path-of-the-ocean/). For this Dryland planner, omit the naval tutorial and Perfection scoring paragraph entirely.

7. **Tell the planner to batch chosen actions, preserve tactical options, and justify each additional call.** In [planner.py](C:/Users/augus/polytopia-claude/harness/polytopia_bridge/planner.py), replace `INSTRUCTIONS` and the duplicated strategy Planning bullet with one authoritative instruction:

   > “Choose useful actions; do not execute actions merely because they are legal. Batch your chosen independent actions. Every index belongs to this snapshot: spending shares one treasury, and a destination blocked now has no selectable move even if another action will free it. Before moving a unit, consider attacks currently available to it. Leave supporting units uncommitted when newly revealed enemies could change their best action. Omit end turn only when you can name a useful follow-up requiring a fresh list, such as training after research, attacking after movement, or occupying a cleared city. Batch compatible enabling actions before that refresh. On the final call, prioritize executable combat, occupation, and spending; newly unlocked actions will otherwise wait until next turn. Current state and legal actions override earlier notes or commentary. An empty list ends the turn.”

   Also separate the retry allowance from `calls_left`: the runner passes `min(2, remaining)` as `max_attempts`, so the first prompt currently reports **2 calls remaining even when 3 remain**. Pass `calls_left=remaining` separately and subtract attempts from that value when building retry prompts.

8. **Expose support capacity and meaningful star math.** In [observe.py](C:/Users/augus/polytopia-claude/harness/polytopia_bridge/observe.py), count supported units using the already-serialized `home` field:

   ```python
   supported = sum(
       u["owner"] == my_id and u.get("home") == [c["x"], c["y"]]
       for u in st["units"]
   )
   ```

   Append `support {supported}/{c['level'] + 1}` and the city-tile occupant to each friendly city. Include `home`, kills, and promotion availability on friendly unit lines. Include movement, range, and abilities for enemies; those fields are serialized but currently omitted from their observation lines.

   Add this instruction:

   > “Budget actions cumulatively from current stars. Income arrives next turn; include Resources only after the level-up that grants it. Before buying growth, identify the resulting population, reward, and remaining recruitment budget.”

   For the fixture, display:

   ```text
   Treasury 12; income next turn +5.
   Capital: pop 0/5; support 3/5; recruitment tile empty.
   ```

   Stop labeling `c["production"]` as total city income: the fixture displays `+1/turn` there despite its only city supporting a reported empire income of +5. Until the field is correctly interpreted, omit that label and retain `me["income"]`.

9. **Make routes legible without inflating every move entry.**

   `dist-to-capital` already exists, but it is Chebyshev tile distance—not travel time, and not a turn lower bound with Riders or roads. Rename it `straight-line tiles`, and show distances to the selected city/village target even before the capital is found.

   Fix the legend collision: enemy cities and crops both use feature `c`. Change the enemy-city feature to `E` in `_map_lines()` and `LEGEND`.

   Add compact auxiliary lines:

   ```text
   ROADS: (x,y) ...
   VISIBLE ENEMY TERRITORY: (x,y) ...
   TARGET village (10,10): #11 at (9,12), straight-line 2 tiles.
   ```

   Roads and ownership are serialized but absent from the map; the fixture’s enemy-owned tiles at `(13,8)` and `(14,8)` are useful northern scouting clues. Do not present their off-screen ruling-city coordinates as a discovered city.

   Replace the exhaustive friendly-territory prose with actionable resource/improvement entries, retaining exact build costs and rewards. This removes repeated terrain descriptions while preserving the information needed for spending.

10. **The sample plan is legal-looking but strategically weak, and its Riding claim needs provenance.**

    In [sample_turn_output.txt](C:/Users/augus/polytopia-claude/docs/sample_turn_output.txt), moving Warrior #1 onto `(11,13)` is good. However:

    - Two hunts spend 4 stars to reach only **2/5 population**, without income, capacity, or reward.
    - Warrior #11 should move to `(10,11)`, putting the northern village `(10,10)` within the next move.
    - Warrior #7’s move to `(10,14)` neither shortens the northern route nor reveals useful nearby terrain; I would move it to `(10,13)`.
    - The fixture has **no Riding**, and still offers research Riding for 5 stars. The sample does not include that research.

    Against the exact stored fixture, my first plan would be:

    ```json
    {"actions": [1, 36, 17, 29]}
    ```

    That researches Riding and makes the three moves above, then requests the fresh list. Next, train one Rider at `(8,13)` for 3 stars and finish other useful newly available actions; otherwise end turn. Treasury: **12 − 5 − 3 = 4**. I would save those 4 stars rather than make partial growth purchases.

    The prompt’s “cheap growth” bias and lack of an explicit target per unit explain the movement/spending weakness. Stale history could explain “Riding is in,” but the captured prompt is absent, so that cause is unproven. Label the sample as an adapted **16×16 Xinxi/Easy fixture**, and capture the exact prompt/state alongside future samples; it does not demonstrate Imperius/Normal/Tiny performance.

11. **Show actual action outcomes and the opponent’s reply.** [Console.step()](C:/Users/augus/polytopia-claude/harness/polytopia_bridge/console.py) currently prints acceptance plus a preview. Acceptance is not an observed combat result.

    In `runner.py`, retain the pre-action state and successful action; when the next state arrives, compare unit IDs, HP, positions, city owners/levels, and treasury before rendering the result. Use the same outcome text in `turn_log`, so replans benefit too. Example output format:

    ```text
    ATTACK #4 → #13: enemy HP 10→0, killed; own HP 10→10; advanced to (6,5)
    CAPTURE (6,5): enemy→ours; enemy cities reported 3→2
    BUILD Hunting: stars 7→5; capital pop 2→3; level 2→3
    ENEMY TURN: lost Warrior #7; #4 HP 10→4; new Archer seen at (7,4)
    ```

    Across the enemy turn, describe an enemy unit disappearing as “no longer visible” unless a kill is established. Add a strategic footer: cities captured, kills/losses, stars remaining, and next siege target.

12. **Reduce terminal noise and make commentary explain the decision.**

    Replace `PLAN_SCHEMA["properties"]["commentary"]["description"]` with:

    > “Write this first: 2–3 short sentences, at most 70 words. State the immediate objective, the decisive action or spending choice and why, and the main threat or reason another call is needed. Distinguish intended actions from completed results. Do not repeat the full action list.”

    Add `--verbose` in [play_domination.py](C:/Users/augus/polytopia-claude/harness/scripts/play_domination.py). By default, print streamed commentary, a compact plan summary, actual execution results, and the strategic footer. Show the full pre-execution action list, notes, token counts, and per-action timing only in verbose mode. This avoids printing each action twice and stops cutting notes mid-word.

    Gate ANSI and in-place thinking updates on `stream.isatty()`; noninteractive output should contain one planning-start line and one completion line.

    Split the long header into two lines, distinguish **reported total enemy cities** from **located cities**, and show visible unit composition. The sample would then say “enemy: 5 reported cities, 0 located; visible: Warrior ×1.” Share objective formatting with `observe.py` so a captured capital does not become “not found yet” again.

    Finally, put the sample’s **42,083 cache-write / 0 cache-read tokens** in diagnostics. That is a cold call; it does not establish the cost or latency of the intended cached steady state.