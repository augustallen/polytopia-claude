The root cause was **committing to a siege without controlling the surrounding army or protecting recruitment cities**. Refusing suicidal attacks was correct; repeatedly staging and healing beside that siege was not. Game 1 succeeded with a much larger economic base and sustained ranged recruitment.

I also checked the raw game-2 log and observation code. Files remain unchanged.

1. **Make a stalled siege trigger a change of objective.**

   Camomo and Musdo were already captured on turns 5 and 8. The missed opportunity was **holding them**, not choosing them instead of Tofork. On turn 11, two Riders and a Warrior moved adjacent to Tofork while the newly spawned Giant was still at Mama. Rider #10 immediately lost 6 HP; Musdo was occupied during the turn-12 enemy reply and captured during turn 13.

   Game 1 had six cities by turn 12, bought Archery on turn 9, and repeatedly recruited Archers. It cleared invasions of Carolo on turns 10 and 14. Its eventual siege worked because that army could kill field units and sustain losses—not because waiting around a capital is inherently effective.

   Replace the entire first bullet in `strategy_domination.md` with:

   > Objective: eliminate the opponent by capturing all their cities. Choose the next operation by what you can take and hold while preserving your recruitment base. Before committing to a siege, name the garrison-breaking force, its arrival turn, the occupier, and the defenders of your threatened cities. If the force is not ready, use the army to intercept approaching enemies, protect expansion, or take a weaker city. Reassess after every enemy reply: if you are losing units or cities without bringing a capture closer, withdraw exposed units and change the operation. Prefer the capital only when its capture is comparably achievable. Stop expansion and growth only when the existing army can finish the remaining cities.

   Delete the siege sentence **“If entry is not possible yet, stage the occupier while clearing threats; do not count an empty city as secured.”** Replace it with:

   > If entry is not possible, keep the occupier outside avoidable enemy attack reach until the breaking force arrives. Staging must have a named purpose and arrival turn; proximity to the capital alone is not progress.

2. **Make saving threatened cities outrank unrelated siege progress.**

   The strongest concrete missed defence is turn 23. Mama contained enemy Defender #29, which would capture next enemy turn. Both Catapults had legal attacks against it: #35 previewed **10 damage, zero effective retaliation**; #36 **10 damage, 6 retaliation**. Starting with #35 offered a credible kill sequence against its 15 HP, followed by a refresh for recruitment. Instead, they killed a Defender and Warrior near Tofork. Mama fell.

   Replace the entire **Defence** bullet with:

   > Defence: before offensive moves, inspect every owned city for an enemy occupant and for enemies that can enter or kill its garrison during the next enemy turn. Evict an enemy occupant before it captures, prioritising your last city and essential recruitment cities over unrelated kills or siege damage. Newly captured forward cities need a healthy garrison and nearby units able to kill approaching attackers; do not send the capturer away until that defence is replaced. A garrison alone is insufficient if several enemies can overwhelm it. Vacate a threatened recruitment tile only when the replacement can be trained this turn and survive the reply. Keep safe city tiles available for recruitment. If a forward city cannot be held or rescued, withdraw valuable units toward a defensible city and stop investing in the doomed position.

   This calls for defending the eastern corridor and killing its attackers first, without requiring extermination of every field unit before any conquest.

3. **Replace capture-only spending with defence, production, and an explicit reserve.**

   The round-4 sentence was:

   > “Before ending the turn, identify the purchase that most shortens the next city capture: a needed unit, its technology, a useful road, or population completing a useful reward.”

   It focuses spending on a distant capture rather than preventing imminent losses. The accompanying rule—

   > “Save only for a named purchase with a cost and an intended turn, or when further spending cannot help before victory.”

   —was not followed: turn 18 banked stars “for next turn’s captures”; turn 19 banked 28 “for units near Tofork”; turn 22 held stars “for replacements.” These were aspirations, not purchase schedules.

   Replace those sentences and the intervening **“Buy it when affordable and timely.”** with:

   > Before ending the turn, fund the immediate operation: save a threatened city, kill its attackers, recruit missing combat roles, or complete a useful city reward. Check every city for useful recruitment, cumulatively budgeting the purchases. If a friendly occupant blocks needed recruitment, decide whether it can safely move, then refresh and train this turn. Research defensive or supporting units when those roles are missing. Any reserve must name the purchase, its full remaining cost, recruitment city if applicable, and intended turn; spend surplus beyond that reserve when it improves the position. Saving for an unspecified capture or replacement is not a purchase plan.

   Also replace **“Stop recruiting units that cannot reach the remaining fight before it ends.”** with:

   > Stop recruiting only when additional units cannot improve either defence or the remaining conquest before victory.

   There were real tile constraints: turn 19’s second call offered no training; turn 22 began with all three city tiles occupied. But turn 20’s second call offered recruitment at both Mama and Modolo, and turn 22 moved the Mama Catapult away without refreshing to recruit.

4. **Evaluate recovery against the enemy reply, not against full health.**

   Recovery became a holding pattern. Rider #13 healed from 4→8 HP on turn 11, was reduced to 3 by the reply, returned to Musdo on turn 12, and died. Warrior #7 repeatedly recovered at `(5,7)` while enemies continued attacking. Swordsman #30 recovered on turns 21–22 while a Defender approached Mama.

   Replace the entire **Fighting** bullet with:

   > Fighting: evaluate the whole exchange through the next enemy reply. Prioritise kills that save cities, remove dangerous attackers, or permit occupation, even when the opening hit takes more damage than it deals. Focus fire; earlier hits change later damage and retaliation. Use ranged softening before a melee finisher when it improves survival. Recover only when the expected healing and resulting position are more useful than attacking, screening, reinforcing, or retreating. Do not repeatedly heal under attacks that erase the recovery; withdraw toward support or remove the attacker. Full health is not a prerequisite for a useful attack. Preserve units for a named next action, not merely to avoid losing HP.

   Append to `INSTRUCTIONS`:

   > Before assigning recover or leaving a combat unit idle, check whether it can help save a city or complete a kill, including after a move and refresh. Reassess recurring healing or staging plans when the enemy reply undoes their benefit.

   Do not impose an attack quota: the low attack count was largely a consequence of poor positioning and army composition.

5. **Allow supporting units to solve the field battle, independently of the capital siege.**

   Game 2 recruited Riders after identifying their inability to break Tofork, researched Mathematics by turn 14, but never researched Archery or Shields. It had no Archer screen and no recruited durable garrison. Game 1’s Archers were useful well before they could collectively kill the capital garrison.

   Replace:

   > “Add more Archers only when their arrival produces a credible same-turn kill and occupation.”

   with:

   > Buy Archers when their arrival enables useful focus fire against field units, protects cities, or completes a siege kill. Buy Shields and Defenders when durable garrisons free the mobile army or protect threatened recruitment cities. Defenders hold positions; pair them with units that can kill attackers. Do not keep buying Riders for a stationary siege unless they have a specific interception, finishing, or occupation role.

   Replace **“Against a walled city with a healthy Swordsman, compare…”** through **“…Smithery and Swordsmen.”** with:

   > When current attacks cannot break a garrison efficiently, compare the earliest supported operation using existing units, a Giant level-up, Forestry -> Mathematics and a Catapult, or the remaining Smithery prerequisites and Swordsmen. Include research, training, travel, protection, and occupation in the comparison. Buy the force needed for the current field battle while assembling the siege force.

6. **Adapt the opening to contact and terrain; do not mandate an unseen turn-5 all-in.**

   The capital was not discovered until turn 9, already walled. The transcript therefore cannot establish that a turn-5–8 Warrior rush would have succeeded. Earlier split scouting could have exposed that option: turn 4’s claim that Bardur “must be” east had no basis, and contact actually arrived from the south.

   A Giant plan was reasonable: Farming on turn 9 brought Mama to level 4, but **did not produce a Giant**. The turn-11 ruin completed it. The error was treating the future Giant as sufficient reason to expose the army immediately.

   Append to the **Opening** bullet:

   > Split early scouting across useful unexplored approaches rather than sending every unit along the same route; enemy contacts are evidence about direction, not proof of the capital's location. When an enemy city is discovered close by, check whether current units and near-term reinforcements can kill its garrison, enter, and survive before committing to an immediate assault. A short geometric distance alone does not justify an all-in. If walls or durable defenders already make the assault unproductive, secure accessible villages and their approaches while completing the quickest supported Giant or siege plan. Do not wait beside the enemy city for that investment to mature.

7. **Extend the post-game Catapult rule to ranged attacks and actual approach paths.**

   The added melee rule addresses turn 15’s death at Camomo, but game 2 also shows the broader failure: the Modolo Catapult trained on turn 21 was reduced to 1 HP immediately; the Bulinrø Catapult trained on turn 24 died immediately.

   Replace the two sentences starting **“A Catapult has 0 defence…”** and **“block every approach tile…”** with:

   > A Catapult has 0 defence. Before training or ending its turn, inspect enemy move-and-attack reach, ranged attacks, roads, and approaches opened by killing your screen. Choose a position where it can survive until its first useful shot. An adjacent friendly unit does not protect every approach, and melee screens do not stop ranged fire. If no protected deployment is available, train a durable defender or supporting attacker first, or deploy the Catapult farther back. Range to the target is useful only when the Catapult survives to fire.

8. **Keep the previews; clarify that displayed defence already reflects the position.**

   “Def 12” was not invented. The raw log gives the walled Defender `defence: 12`. On turn 12, the three available capital attacks each dealt **1**, taking **12, 13, and 12** respectively. Rejecting them was correct.

   The overgeneralisation was “only catapults can hurt it” and applying that fear to other targets. Turn 19 itself demonstrates useful combined attacks: Giant softening followed by the Warrior secured Bulinrø.

   In `rules.md`, replace:

   > “Damage is proportional: attack x (attacker hp / max hp) vs defence x (defender hp / max hp) x terrain bonus. The action list shows the exact damage an attack deals and the retaliation you take.”

   with:

   > Unit descriptions report engine-calculated attack and defence for the current position; do not multiply displayed defence by city or terrain bonuses again. Judge attacks by their legal-action damage and retaliation previews. A bad preview against one garrison does not rule out attacking field units or finishing that garrison after supporting hits. Earlier attacks change later previews.

   In `observe.py`, replace `def {u['defence']:g}` in both existing-unit displays with:

   ```python
   defence-now {u['defence']:g}
   ```

   Leave base recruitment statistics distinct.

9. **Fix population presentation before giving stronger Giant instructions.**

   `population_to_level` is populated from `PopulationNeededToUpgradeCity()`. The logs demonstrate that it is **remaining population**, whereas the renderer presents it as a denominator. Mama appeared as `pop 3/1` before the farm and `pop 4/1` afterward. This helps explain the mistaken automatic-Giant prediction.

   In `observe.py`, replace:

   ```python
   f"  {c['name']} {xy((c['x'], c['y']))} level {c['level']}, pop {c['population']}/{c['population_to_level']} "
   f"to next level, supports {supported}/{c['level'] + 1} units, city tile {occ_s}"
   ```

   with:

   ```python
   f"  {c['name']} {xy((c['x'], c['y']))} level {c['level']}, population {c['population']}, "
   f"needs {c['population_to_level']} more pop to level up, supports {supported}/{c['level'] + 1} units, city tile {occ_s}"
   ```

   Append to the **Economy** bullet:

   > For a Giant plan, name the city, remaining population, affordable builds, and resulting reward. Recheck the city after Population Growth; reaching level 4 does not automatically produce a Giant.

   Do not infer that Modolo’s missing population on turn 22 had an immediately legal cheap completion: the logged Lumber Hut option belonged to Bulinrø.

10. **Fix turn-start observation readiness; clean execution did not guarantee a settled economy snapshot.**

    Turn 1’s planner state showed 1 star and no purchases; its first move changed stars **1→4**. Turn 10 similarly began at 1 star, leading to “Broke…staging,” then the first move changed stars **1→10**. These are strong evidence that planning sometimes preceded completion of turn-start processing. The precise engine timing needs verification.

    This needs a bridge/runner readiness fix, not permission for the model to invent spendable income. Use this exact implementation requirement:

    > Invoke the planner only after the local player's turn-start processing has completed. Serialize the treasury, city population, pending rewards, and legal actions from that settled state. Refresh before planning when turn-start processing is still pending; do not make a gameplay action necessary to receive the settled observation.

    Replace the observation phrase **“+{me['income']} arrive next turn”** with:

    ```python
    income {me['income']}/turn
    ```

    Replace the `INSTRUCTIONS` parenthetical **“budget cumulatively from current stars; income arrives next turn”** with:

    > budget cumulatively from the latest reported spendable stars; never add income speculatively, and re-budget after refreshed state or reward changes

    This explains some early under-spending. It does **not** excuse holding 38–54 stars while recruitment and city defence needed attention.