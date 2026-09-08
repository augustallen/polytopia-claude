Read-only review complete; no files changed. The main problem was delayed conversion of income into siege power, compounded by poor occupation timing. Round 3 addresses several causes, but the current prompt still omits Catapults.

1. **Add an explicit spending decision; support caps do not explain the bank.** In the transcript, T14 spends 6 of 21 stars on two Archers; T15 spends 6 of 31; T16 spends 13 of 44 on Climbing and an Archer; T17 spends 19 of 50 on Forestry and an Archer. All execute successfully. The model mentions *capacity* as a growth benefit, but never says a support cap prevents recruitment. Occupied recruitment tiles are a real constraint; a general support-cap explanation is unsupported. The spectator transcript omits the complete legal lists, so it cannot establish every unselected purchase.

   The current strategy’s “build the unit that supplies the missing role,” “Giants or stronger units when basic attacks cannot break the defence,” and “Reserve the stars for this turn’s decisive recruitment, research or roads” point toward the remedy. None explicitly requires converting surplus into that remedy. The last sentence can even encourage continued reservation. Replace it in [strategy_domination.md](harness/polytopia_bridge/strategy_domination.md) with:

   > Before ending the turn, identify the purchase that most shortens the next city capture: a needed unit, its technology, a useful road, or population completing a useful reward. Buy it when affordable and timely. Save only for a named purchase with a cost and intended turn, or when further spending cannot help before victory. An occupied recruitment tile and a full support allocation are different constraints; check the city lines and legal training actions.

   Do **not** impose “spend all stars.” The T24 Catapult contributes immediately on T25; the T25 Rider trained far south contributes nothing before victory. The final 114-star balance is less informative than the missed purchases before T19.

2. **Replace the vague siege technology advice with a conditional Catapult path.** Wegoth has a Swordsman by T12. T14–17 mostly involve clearing counterattackers and assembling Archers, rather than sustained fire against the capital itself. Some defensive fighting was necessary, especially at Carolo; the avoidable delay was continuing the same army composition.

   Replace the Technology bullet’s sentences beginning “Hunting -> Archery” through “Knights are a situational answer” with:

   > Hunting -> Archery provides supporting damage. Against a walled city with a healthy Swordsman, compare the earliest turn you can kill the garrison and occupy the city using your existing army, Forestry -> Mathematics for a Catapult, population completing a Giant, or the remaining prerequisites for Smithery and Swordsmen. Prefer a protected Catapult when existing ranged units cannot finish the garrison promptly; train it near the target, ideally already within range 3. Catapults cannot move and attack on the same turn. Prefer a Giant when an affordable nearby level-up delivers it sooner, or Swordsmen when their remaining research and travel are quicker and they supply a durable occupier. Add more Archers only when their arrival produces a credible same-turn kill and occupation.

   This is supported by the actual fight: Catapult #38 repeatedly deals 10, then an Archer deals 6 and kills the 15-HP garrison. Giants arrive on T20 and eventually secure Resres; they were useful, but the transcript does not establish that an earlier Giant was cheaper or faster than Mathematics. Likewise, it does not establish an earlier Smithery purchase as the best alternative.

3. **Require completing affordable research chains within the available calls.** T17 had 50 stars. The observed prices were Forestry 16, Mathematics 22 and Catapult 8: **46 total**. Instead, the model researched Forestry, trained an Archer on Carolo’s recruitment tile, and ended after one call. Mathematics and the first Catapult arrived T18; the Catapult first fired T19 from **(7,6)**, already within range of Wegoth **(8,3)**.

   Earlier execution remains conditional on the refreshed legal lists, but this is a concrete missed opportunity. The current instructions already mention “training after research”; make the obligation explicit by inserting after the fresh-list sentence in [planner.py](harness/polytopia_bridge/planner.py):

   > If an affordable research chain unlocks the unit needed for the current fight, use remaining calls to complete the chain and recruit this turn. Keep its intended city tile free; do not fill it with a substitute unit first. Do not end the turn merely because the next prerequisite or recruitment requires a refreshed action list.

4. **Make the occupier a named, reserved unit before firing.** The capital’s garrison dies on T19, T20 and T21, but occupation occurs only T21 and capture T22. T19 explicitly plans to leave it empty “for next turn” and ends with two calls unused. T20 requests a refresh but then discovers nothing can reach the city. These are separate losses from the delayed Catapult. Resres also repeatedly loses fragile occupiers before Giant #44 holds it.

   Round 3’s “plan the kill and the occupation together,” same-turn entry, and no besieger Fortify already address this directly. Strengthen the first sentence of the Siege bullet to:

   > Before firing at a city, name the unit that will occupy it this turn, its approach tile, and the enemy units that could kill it before capture. Reserve that unit’s required movement or attack. If entry is not possible yet, stage the occupier while clearing threats; do not count an empty city as secured. After a ranged kill, use a remaining call for entry when the newly legal move is needed.

   Avoid promising an exact earlier winning turn: enemy replies would change.

5. **Add a short plan-conflict check; retain harmless overkill skips.** The 17 skips comprise:

   | Count | Actual cause |
   |---:|---|
   | 6 | T7: Monument7 placements after that monument had already been placed on T6; delayed reward/state processing also matters here. |
   | 3 | T5 and both T8 calls: two recruits planned on the same city tile. |
   | 1 | T16: Archer #20 receives two ordinary moves, first to (7,7), then (6,6). |
   | 1 | T24: Rider #14 and Archer #35 both target (6,3). |
   | 4 | T19–21 and T25: an earlier attack already killed the garrison. |
   | 1 | T26: the remaining enemy attack becomes unavailable after the final city capture. |

   The current snapshot warning explains destinations blocked **before** execution, but omits conflicts the plan itself creates. Insert:

   > Check the ordered plan for conflicts: choose at most one recruit per city tile and one placement per monument; do not give a unit two ordinary moves or send two units to the same destination unless the first leaves legally. Training occupies the city tile. Earlier attacks can kill a target sooner than its snapshot previews suggest; a skipped excess attack does not mean that attacker spent its action.

   Keep the round-3 monument grouping. Do not add model calls solely to eliminate benign overkill: current revalidation correctly avoids attacking a dead target.

6. **Keep reward-trigger re-queuing; fix its end-turn edge case.** The T7 rejection was not a bad move: a reward became pending after the supplied state. Re-queuing once, answering the trigger and revalidating is the right local response. Requesting state before every plan cannot eliminate a trigger appearing after that request or during planning.

   The implemented fix preserves ordinary steps, but the subsequent unconditional `steps.clear()` discards a re-queued `end_turn`. In [runner.py](harness/polytopia_bridge/runner.py), replace the final clearing condition after `act()` with:

   ```python
   if step.get("kind") == "end_turn" and result.get("ok"):
       steps.clear()
   ```

   Keep the one-retry marker and existing failure handling. This deserves a focused regression case: reject end turn with a pending reward, answer the reward, then execute the retained end turn.

7. **Correct commentary’s rule claims without expanding the mechanics prompt again.** T12 notes and T14 notes claim that shooting an enemy Archer at range 2 avoids retaliation. That is wrong under the current rules; T15’s zero-retaliation Archer kill is valid because it kills the defender. The model also initially mistakes crop (2,6) for a village, sums changing previews as exact damage, and writes planned outcomes into notes as completed facts.

   Round 3 already fixes the retaliation explanation, map legend and outcome reporting. Append to the `PLAN_SCHEMA["properties"]["notes"]["description"]`:

   > Describe unexecuted outcomes conditionally. Do not record a planned kill, capture or purchase as completed; the next state and execution log determine what happened.

   Append to the commentary description:

   > Attribute zero retaliation to the current preview, range advantage or a killing blow, not to being an Archer. Treat snapshot damage totals as estimates.

8. **Finish two spectator fixes that remain in current code.** The new state diffs, compact plans, clamped negative previews and reduced thinking output already address most transcript clutter. Two remaining issues are concrete:

   First, T6 and T21 commentary repeats almost the same paragraph consecutively. `consume_events()` currently forwards both ordinary text and extracted structured commentary to the same callback. That is a plausible cause, although the spectator transcript alone cannot prove which stream supplied each paragraph. In [claude_stream.py](harness/polytopia_bridge/claude_stream.py), replace the `text_delta` forwarding branch with:

   ```python
   elif dt == "text_delta":
       continue  # Spectator commentary comes from StructuredOutput only.
   ```

   Second, the current console still describes an already-captured capital as “not located.” Replace its `obj` assignment in [console.py](harness/polytopia_bridge/console.py) with:

   ```python
   obj = (
       f"enemy capital {cap['name']} at {xy((cap['x'], cap['y']))} lvl {cap['level']}"
       if cap else
       "remaining targets: " + ", ".join(
           f"{c['name']} at {xy((c['x'], c['y']))}" for c in enemy_cities
       ) if enemy_cities else
       "no enemy city currently located"
   )
   ```

9. **Delete redundant or rigid strategy text.** Specifically:

   - Delete the entire **“Early expansion”** bullet. Useful village selection is covered by the opening/overall objective; capture timing belongs in `rules.md`.
   - Delete the entire **“Notes”** bullet. `INSTRUCTIONS` already establishes state precedence, and the schema defines notes.
   - Delete **“Move as a group of 3-5 units, not a trickle.”** The required siege roles and arrival times are more useful than a fixed count.
   - Delete **“Never disband units.”** No evidence here makes disbanding necessary, but an absolute prohibition is unnecessary. Retain the rest of that bullet about harness-managed rewards.
   - Delete **“Do not build walls or many defenders.”** The preceding threat-based defence guidance already supplies the decision criterion.

   Keep the opening, economic reward targeting, melee/ranged occupation distinction and threat-based defence. Those address observed mistakes; they are not unnecessary prompt weight.