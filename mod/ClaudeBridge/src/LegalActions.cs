using Polytopia.Data;

namespace ClaudeBridge;

/// <summary>
/// Enumerates every command the engine would accept from the local player right now, using the
/// game's own option generators and each command's IsValid, so the list is exactly what the UI offers.
/// </summary>
internal static class LegalActions
{
    public static List<Dictionary<string, object?>> Enumerate(GameState gs, PlayerState player)
    {
        var actions = new List<Dictionary<string, object?>>();
        var seen = new HashSet<string>();
        var gld = gs.GameLogicData;
        var map = gs.Map;
        byte pid = player.Id;
        int w = map.Width;

        void AddIfValid(CommandBase cmd, Action<Dictionary<string, object?>>? annotate = null)
        {
            if (!cmd.IsValid(gs)) return;
            var a = CommandCodec.Encode(cmd);
            if (!seen.Add(CommandCodec.Key(a))) return;
            annotate?.Invoke(a);
            actions.Add(a);
        }

        // A pending trigger (city level-up reward, incoming peace request) blocks every other command.
        if (gs.TryGetPendingCommandTrigger(pid, out var trigger) && trigger.type != CommandTriggerType.None)
        {
            switch (trigger.type)
            {
                case CommandTriggerType.CityLevelUp:
                    foreach (var reward in Enum.GetValues<CityReward>())
                        if (reward != CityReward.None)
                            AddIfValid(new CityRewardCommand(pid, reward, trigger.coordinates));
                    break;
                case CommandTriggerType.PeaceRequest:
                    AddIfValid(new PeaceRequestResponseCommand(pid, trigger.opponentId, true));
                    AddIfValid(new PeaceRequestResponseCommand(pid, trigger.opponentId, false));
                    break;
            }
            if (actions.Count > 0) return actions;
            // Nothing validated: fall through rather than leave the agent with no moves at all.
        }

        // Research
        var unlockable = gld.GetUnlockableTech(player, gs);
        if (unlockable != null)
        {
            foreach (var tech in unlockable)
            {
                AddIfValid(new ResearchCommand(pid, tech.type), a =>
                {
                    a["cost"] = gld.GetTechPrice(tech, player, gs);
                    var units = new List<string>();
                    if (tech.unitUnlocks != null) foreach (var u in tech.unitUnlocks) units.Add(u.type.ToString());
                    var improvements = new List<string>();
                    if (tech.improvementUnlocks != null) foreach (var im in tech.improvementUnlocks) improvements.Add(im.type.ToString());
                    var techs = new List<string>();
                    if (tech.techUnlocks != null) foreach (var nt in tech.techUnlocks) techs.Add(nt.type.ToString());
                    a["unlocks_units"] = units;
                    a["unlocks_improvements"] = improvements;
                    a["unlocks_techs"] = techs;
                });
            }
        }

        var tiles = map.Tiles;
        for (int i = 0; i < tiles.Length; i++)
        {
            var tile = tiles[i];
            if (tile == null) continue;

            var unit = tile.unit;
            if (unit != null && unit.owner == pid)
            {
                int movement = UnitDataExtensions.GetMovement(unit, gs);
                var moves = UnitDataExtensions.GetMovementOptions(unit, gs, movement);
                if (moves != null)
                    foreach (var to in moves)
                        AddIfValid(new MoveCommand(pid, unit, to));

                int range = UnitDataExtensions.GetRange(unit, gs);
                var targets = UnitDataExtensions.GetAttackOptions(unit, gs, range, false);
                if (targets != null)
                {
                    foreach (var target in targets)
                    {
                        AddIfValid(new AttackCommand(pid, unit, target), a =>
                        {
                            int idx = target.Y * w + target.X;
                            var defender = idx >= 0 && idx < tiles.Length ? tiles[idx]?.unit : null;
                            if (defender == null) return;
                            var br = BattleHelpers.GetBattleResults(gs, unit, defender, true, false);
                            // health and damage are in tenths in the engine; report in-game numbers
                            a["target_unit_id"] = defender.id;
                            a["target_type"] = defender.type.ToString();
                            a["target_hp"] = defender.health / 10.0;
                            a["damage"] = br.attackDamage / 10.0;
                            a["retaliation"] = br.retaliationDamage / 10.0;
                            a["kills"] = defender.health <= br.attackDamage;
                        });
                    }
                }

                // capture, recover, promote, disband, examine ruins, abilities, ...
                var unitActions = CommandUtils.GetUnitActions(gs, player, tile, false);
                if (unitActions != null)
                    foreach (var cmd in unitActions)
                        AddIfValid(cmd);
            }

            var trainable = CommandUtils.GetTrainableUnits(gs, player, tile, false);
            if (trainable != null)
            {
                foreach (var cmd in trainable)
                {
                    AddIfValid(cmd, a =>
                    {
                        var train = cmd.TryCast<TrainCommand>();
                        if (train == null || !gld.TryGetData(train.Type, out UnitData? data) || data == null) return;
                        // UnitData keeps these in tenths (Warrior: health 100, attack 20); report in-game numbers.
                        a["cost"] = data.cost;
                        a["hp"] = data.health / 10.0;
                        a["attack"] = data.attack / 10.0;
                        a["defence"] = data.defence / 10.0;
                        a["movement"] = data.movement;
                        a["range"] = UnitDataExtensions.GetRange(data);
                        var abilities = new List<string>();
                        if (data.unitAbilities != null) foreach (var ab in data.unitAbilities) abilities.Add(ab.ToString());
                        a["abilities"] = abilities;
                    });
                }
            }

            var buildable = CommandUtils.GetBuildableImprovements(gs, player, tile, false);
            if (buildable != null)
                foreach (var cmd in buildable)
                    AddIfValid(cmd, a => AnnotateBuild(gld, cmd, a));

            var abilities = CommandUtils.GetImprovementAbilities(gs, player, tile, false);
            if (abilities != null)
                foreach (var cmd in abilities)
                    AddIfValid(cmd, a => AnnotateBuild(gld, cmd, a));

            // Harvests are hidden improvements that the generic buildable list can skip.
            if (tile.owner == pid && tile.improvement == null)
            {
                var resource = tile.GetResource(gs, pid);
                var harvests = resource != null ? gld.GetImprovementForResource(resource.type) : null;
                if (harvests != null)
                    foreach (var imp in harvests)
                        if (imp != null && imp.hidden)
                            AddIfValid(new BuildCommand(pid, imp.type, tile.coordinates), a => AnnotateBuild(gld, imp, a));
            }
        }

        // Diplomacy with every player we have met
        foreach (var other in gs.PlayerStates)
        {
            if (other.Id == pid || other.Id == PlayerState.NATURE_PLAYER_ID) continue;
            if (player.knownPlayers == null || !player.knownPlayers.Contains(other.Id)) continue;
            var diplomacy = CommandUtils.GetDiplomacyCommandsForOpponent(gs, player, other.Id, false);
            if (diplomacy != null)
                foreach (var cmd in diplomacy)
                    AddIfValid(cmd);
        }

        AddIfValid(new EndTurnCommand(pid));
        return actions;
    }

    static void AnnotateBuild(GameLogicData gld, CommandBase cmd, Dictionary<string, object?> a)
    {
        var build = cmd.TryCast<BuildCommand>();
        if (build == null || !gld.TryGetData(build.Type, out ImprovementData? data) || data == null) return;
        AnnotateBuild(gld, data, a);
    }

    static void AnnotateBuild(GameLogicData gld, ImprovementData data, Dictionary<string, object?> a)
    {
        a["cost"] = ResourceDataUtils.GetCurrencyCost(data);
        a["population"] = ResourceDataUtils.GetPopulationReward(data);
        var stars = ResourceDataUtils.GetCurrencyReward(data);
        if (stars > 0) a["stars"] = stars;
    }
}
