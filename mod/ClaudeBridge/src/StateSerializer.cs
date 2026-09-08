using Polytopia.Data;

namespace ClaudeBridge;

/// <summary>
/// GameState -> plain dictionaries for System.Text.Json. Everything is filtered to what the local
/// player has explored so the agent sees exactly what a human at the screen would.
/// </summary>
internal static class StateSerializer
{
    public static object BuildStateMessage(GameState gs, ClientBase client)
    {
        var me = LocalPlayer(gs, client);
        return new Dictionary<string, object?>
        {
            ["type"] = "state",
            ["turn"] = gs.CurrentTurn,
            ["player"] = me.Id,
            ["roster"] = Roster(gs),
            ["state"] = Build(gs, me),
            ["legal_actions"] = LegalActions.Enumerate(gs, me),
        };
    }

    public static object BuildGameOverMessage(GameState gs, ClientBase client)
    {
        var me = LocalPlayer(gs, client);
        gs.TryGetWinner(out var winner);
        return new Dictionary<string, object?>
        {
            ["type"] = "game_over",
            ["turn"] = gs.CurrentTurn,
            ["player"] = me.Id,
            ["winner"] = winner?.Id,
            ["won"] = winner != null && winner.Id == me.Id,
            ["score"] = me.score,
            ["roster"] = Roster(gs),
            ["players"] = Players(gs, me),
        };
    }

    static PlayerState LocalPlayer(GameState gs, ClientBase client) =>
        Bridge.LocalSeat(gs, client) ?? GameManager.LocalPlayer ?? client.GetCurrentLocalPlayer();

    /// <summary>Who is in the game, seat-neutral: the same list whichever player is local.</summary>
    public static List<object> Roster(GameState gs)
    {
        var list = new List<object>();
        foreach (var p in gs.PlayerStates)
        {
            if (p.Id == PlayerState.NATURE_PLAYER_ID) continue;
            list.Add(new Dictionary<string, object?>
            {
                ["id"] = p.Id,
                ["tribe"] = p.tribe.ToString(),
                ["name"] = p.UserName,
                ["is_bot"] = p.AutoPlay,
                ["alive"] = p.killedTurn == 0 && p.resignedTurn <= 0,
            });
        }
        return list;
    }

    static Dictionary<string, object?> Build(GameState gs, PlayerState me)
    {
        var gld = gs.GameLogicData;
        var settings = gs.Settings;
        var map = gs.Map;
        byte pid = me.Id;
        int w = map.Width, h = map.Height;

        var tiles = new List<object>(w * h);
        var units = new List<object>();
        var cities = new List<object>();
        var all = map.Tiles;
        for (int i = 0; i < all.Length; i++)
        {
            var tile = all[i];
            if (tile == null || !tile.GetExplored(pid)) continue;

            var t = new Dictionary<string, object?>
            {
                ["x"] = tile.coordinates.X,
                ["y"] = tile.coordinates.Y,
                ["terrain"] = tile.terrain.ToString(),
                ["owner"] = tile.owner,
            };
            if (tile.HasRoad) t["road"] = true;
            if (tile.hasRoute) t["route"] = true;
            if (tile.rulingCityCoordinates.IsValid(w, h)) t["city"] = CommandCodec.XY(tile.rulingCityCoordinates);

            var res = tile.GetResource(gs, pid);
            if (res != null) t["resource"] = res.type.ToString();

            var imp = tile.improvement;
            if (imp != null)
            {
                t["improvement"] = imp.type.ToString();
                if (imp.type == ImprovementData.Type.City)
                {
                    if (tile.owner == 0) t["village"] = true;
                    else cities.Add(City(tile, imp));
                }
            }

            if (tile.effects != null && tile.effects.Count > 0)
            {
                var effects = new List<string>();
                foreach (var e in tile.effects) effects.Add(e.ToString());
                t["effects"] = effects;
            }
            tiles.Add(t);

            var unit = tile.unit;
            if (unit != null && (unit.owner == pid || !unit.IsInvisible(gs, pid)))
                units.Add(Unit(gs, gld, unit, pid, w, h));
        }

        var techs = new List<string>();
        var unlocked = gld.GetUnlockedTech(me);
        if (unlocked != null) foreach (var tech in unlocked) techs.Add(tech.type.ToString());

        var meD = new Dictionary<string, object?>
        {
            ["id"] = pid,
            ["tribe"] = me.tribe.ToString(),
            ["stars"] = me.Currency,
            ["income"] = ResourceDataUtils.CalculateIncomeFor(gs, pid),
            ["score"] = me.score,
            ["techs"] = techs,
        };

        var settingsD = new Dictionary<string, object?>
        {
            ["map_width"] = w,
            ["map_height"] = h,
            ["map_size"] = settings.MapSize,
            ["game_mode"] = settings.BaseGameMode.ToString(),
            ["game_type"] = settings.GameType.ToString(),
            ["difficulty"] = settings.Difficulty.ToString(),
            ["opponents"] = settings.OpponentCount,
            ["turn_limit"] = settings.rules?.TurnLimit,
            ["score_limit"] = settings.rules?.ScoreLimit,
        };

        Dictionary<string, object?>? pending = null;
        if (gs.TryGetPendingCommandTrigger(pid, out var trigger) && trigger.type != CommandTriggerType.None)
        {
            pending = new Dictionary<string, object?>
            {
                ["type"] = trigger.type.ToString(),
                ["at"] = CommandCodec.XY(trigger.coordinates),
                ["opponent"] = trigger.opponentId,
            };
        }

        return new Dictionary<string, object?>
        {
            ["turn"] = gs.CurrentTurn,
            ["settings"] = settingsD,
            ["me"] = meD,
            ["players"] = Players(gs, me),
            ["tiles"] = tiles,
            ["cities"] = cities,
            ["units"] = units,
            ["pending_trigger"] = pending,
        };
    }

    static Dictionary<string, object?> City(TileData tile, ImprovementState imp)
    {
        var rewards = new List<string>();
        if (imp.rewards != null) foreach (var r in imp.rewards) rewards.Add(r.ToString());
        return new Dictionary<string, object?>
        {
            ["x"] = tile.coordinates.X,
            ["y"] = tile.coordinates.Y,
            ["name"] = imp.name,
            ["owner"] = tile.owner,
            ["level"] = imp.level,
            // xp is progress toward the next level; population is the lifetime total.
            ["population"] = imp.xp,
            ["population_total"] = imp.population,
            ["population_to_level"] = tile.PopulationNeededToUpgradeCity(),
            ["production"] = imp.production,
            ["border_size"] = imp.borderSize,
            ["is_capital"] = tile.capitalOf == tile.owner,
            ["connected_to_capital"] = tile.capitalOf == tile.owner || imp.connectedToCapitalOfPlayer == tile.owner,
            ["walls"] = ImprovementDataExtensions.HasReward(imp, CityReward.CityWall),
            ["rewards"] = rewards,
        };
    }

    static Dictionary<string, object?> Unit(GameState gs, GameLogicData gld, UnitState u, byte pid, int w, int h)
    {
        gld.TryGetData(u.type, out UnitData? data);
        var d = new Dictionary<string, object?>
        {
            ["id"] = u.id,
            ["type"] = u.type.ToString(),
            ["owner"] = u.owner,
            ["x"] = u.coordinates.X,
            ["y"] = u.coordinates.Y,
            // The engine keeps health in tenths and attack/defence in hundredths; report the in-game numbers.
            ["hp"] = u.health / 10.0,
            ["max_hp"] = UnitDataExtensions.GetMaxHealth(u, gs) / 10.0,
            ["attack"] = UnitDataExtensions.GetAttack(u, gs) / 100.0,
            ["defence"] = UnitDataExtensions.GetDefence(u, gs) / 100.0,
            ["movement"] = UnitDataExtensions.GetMovement(u, gs),
            ["range"] = UnitDataExtensions.GetRange(u, gs),
            ["veteran"] = u.promotionLevel > 0,
            ["kills"] = u.xp,
        };
        if (u.owner == pid)
        {
            d["moved"] = u.moved;
            d["attacked"] = u.attacked;
            d["can_move"] = u.CanMove();
            d["can_attack"] = u.CanAttack();
            if (u.home.IsValid(w, h)) d["home"] = CommandCodec.XY(u.home);
        }
        if (u.effects != null && u.effects.Count > 0)
        {
            var effects = new List<string>();
            foreach (var e in u.effects) effects.Add(e.ToString());
            d["effects"] = effects;
        }
        if (data?.unitAbilities != null && data.unitAbilities.Count > 0)
        {
            var abilities = new List<string>();
            foreach (var a in data.unitAbilities) abilities.Add(a.ToString());
            d["abilities"] = abilities;
        }
        if (u.passengerUnit != null) d["passenger"] = u.passengerUnit.type.ToString();
        return d;
    }

    static List<object> Players(GameState gs, PlayerState me)
    {
        var list = new List<object>();
        foreach (var p in gs.PlayerStates)
        {
            if (p.Id == PlayerState.NATURE_PLAYER_ID) continue;
            var d = new Dictionary<string, object?>
            {
                ["id"] = p.Id,
                ["tribe"] = p.tribe.ToString(),
                ["name"] = p.UserName,
                ["is_bot"] = p.AutoPlay,
                ["score"] = p.score,
                ["cities"] = p.cities,
                ["kills"] = p.kills,
                ["killed_turn"] = p.killedTurn,
                ["alive"] = p.killedTurn == 0 && p.resignedTurn <= 0,
                ["known"] = p.Id == me.Id || (me.knownPlayers != null && me.knownPlayers.Contains(p.Id)),
            };
            if (p.Id == me.Id)
            {
                d["is_me"] = true;
                d["stars"] = p.Currency;
            }
            else if (me.relations != null && me.relations.TryGetValue(p.Id, out var rel) && rel != null)
            {
                d["relation"] = rel.State.ToString();
            }
            list.Add(d);
        }
        return list;
    }
}
