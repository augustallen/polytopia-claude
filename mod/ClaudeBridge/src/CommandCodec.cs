using System.Text;
using System.Text.Json;
using Polytopia.Data;

namespace ClaudeBridge;

/// <summary>
/// Two-way mapping between engine commands and the wire format. LegalActions encodes commands the
/// engine enumerated; ActionExecutor decodes what the agent sends back. Keeping both directions here
/// guarantees anything advertised as legal can be round-tripped.
///
/// Wire shape: {"kind": "move", "unit_id": 12, "to": [4, 7]}. Coordinates are always [x, y].
/// </summary>
internal static class CommandCodec
{
    static readonly Dictionary<string, CommandType> KindLookup =
        System.Enum.GetValues<CommandType>().ToDictionary(t => KindOf(t), t => t);

    /// <summary>CommandType.HealOthers -> "heal_others"</summary>
    public static string KindOf(CommandType type)
    {
        var name = type.ToString();
        var sb = new StringBuilder(name.Length + 4);
        for (int i = 0; i < name.Length; i++)
        {
            if (i > 0 && char.IsUpper(name[i]) && !char.IsUpper(name[i - 1])) sb.Append('_');
            sb.Append(char.ToLowerInvariant(name[i]));
        }
        return sb.ToString();
    }

    public static int[] XY(WorldCoordinates c) => new[] { c.X, c.Y };

    // ------------------------------------------------------------------ encode

    public static Dictionary<string, object?> Encode(CommandBase cmd)
    {
        var type = cmd.GetCommandType();
        var d = new Dictionary<string, object?> { ["kind"] = KindOf(type) };
        switch (type)
        {
            case CommandType.Move:
            {
                var c = cmd.Cast<MoveCommand>();
                d["unit_id"] = c.UnitId; d["from"] = XY(c.From); d["to"] = XY(c.To);
                break;
            }
            case CommandType.Attack:
            {
                var c = cmd.Cast<AttackCommand>();
                d["unit_id"] = c.UnitId; d["from"] = XY(c.Origin); d["target"] = XY(c.Target);
                break;
            }
            case CommandType.Capture:
            {
                var c = cmd.Cast<CaptureCommand>();
                d["unit_id"] = c.UnitId; d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.Train:
            {
                var c = cmd.Cast<TrainCommand>();
                d["unit_type"] = c.Type.ToString(); d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.Upgrade:
            {
                var c = cmd.Cast<UpgradeCommand>();
                d["unit_type"] = c.Type.ToString(); d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.Build:
            {
                var c = cmd.Cast<BuildCommand>();
                d["improvement"] = c.Type.ToString(); d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.Research:
                d["tech"] = cmd.Cast<ResearchCommand>().Type.ToString();
                break;
            case CommandType.CityReward:
            {
                var c = cmd.Cast<CityRewardCommand>();
                d["reward"] = c.Reward.ToString(); d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.PeaceRequestResponse:
            {
                var c = cmd.Cast<PeaceRequestResponseCommand>();
                d["opponent"] = c.OpponentId; d["accept"] = c.Accepted;
                break;
            }
            case CommandType.PeaceTreaty:
            {
                var c = cmd.Cast<PeaceTreatyCommand>();
                d["opponent"] = c.OpponentId; d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.EstablishEmbassy:
            {
                var c = cmd.Cast<EstablishEmbassyCommand>();
                d["opponent"] = c.OpponentId; d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.DestroyEmbassy:
            {
                var c = cmd.Cast<DestroyEmbassyCommand>();
                d["opponent"] = c.OpponentId; d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.BreakPeace:
            {
                var c = cmd.Cast<BreakPeaceCommand>();
                d["opponent"] = c.OpponentId; d["at"] = XY(c.Coordinates);
                break;
            }
            case CommandType.ClearTileEffect:
            {
                var c = cmd.Cast<ClearTileEffectCommand>();
                d["at"] = XY(c.Coordinates); d["effect"] = c.Effect.ToString();
                break;
            }
            case CommandType.EndTurn:
            case CommandType.StartMatch:
            case CommandType.EndMatch:
            case CommandType.Resign:
                break;
            default:
                if (TryGetCoordinates(cmd, type, out var at)) d["at"] = XY(at);
                break;
        }
        return d;
    }

    /// <summary>Every remaining command is "player + one coordinate".</summary>
    static bool TryGetCoordinates(CommandBase cmd, CommandType type, out WorldCoordinates at)
    {
        switch (type)
        {
            case CommandType.Recover: at = cmd.Cast<RecoverCommand>().Coordinates; return true;
            case CommandType.HealOthers: at = cmd.Cast<HealOthersCommand>().Coordinates; return true;
            case CommandType.Destroy: at = cmd.Cast<DestroyCommand>().Coordinates; return true;
            case CommandType.Disband: at = cmd.Cast<DisbandCommand>().Coordinates; return true;
            case CommandType.Promote: at = cmd.Cast<PromoteCommand>().Coordinates; return true;
            case CommandType.ExamineRuins: at = cmd.Cast<ExamineRuinsCommand>().Coordinates; return true;
            case CommandType.FreezeArea: at = cmd.Cast<FreezeAreaCommand>().Coordinates; return true;
            case CommandType.BreakIce: at = cmd.Cast<BreakIceCommand>().Coordinates; return true;
            case CommandType.Stay: at = cmd.Cast<StayCommand>().Coordinates; return true;
            case CommandType.Explode: at = cmd.Cast<ExplodeCommand>().Coordinates; return true;
            case CommandType.Boost: at = cmd.Cast<BoostCommand>().Coordinates; return true;
            case CommandType.Decompose: at = cmd.Cast<DecomposeCommand>().Coordinates; return true;
            case CommandType.Hide: at = cmd.Cast<HideCommand>().Coordinates; return true;
            case CommandType.Disembark: at = cmd.Cast<DisembarkCommand>().Coordinates; return true;
            case CommandType.Flood: at = cmd.Cast<FloodCommand>().Coordinates; return true;
            case CommandType.Swarm: at = cmd.Cast<SwarmCommand>().Coordinates; return true;
            default: at = default; return false;
        }
    }

    /// <summary>Identity of an action for de-duplication: the wire fields only, no annotations.</summary>
    public static string Key(Dictionary<string, object?> a)
    {
        var sb = new StringBuilder();
        foreach (var kv in a.OrderBy(kv => kv.Key, StringComparer.Ordinal))
        {
            sb.Append(kv.Key).Append('=');
            if (kv.Value is int[] xy) sb.Append(xy[0]).Append(',').Append(xy[1]);
            else sb.Append(kv.Value);
            sb.Append('|');
        }
        return sb.ToString();
    }

    // ------------------------------------------------------------------ decode

    public static CommandBase? Decode(JsonElement a, GameState gs, byte pid, out string error)
    {
        error = "";
        if (a.ValueKind != JsonValueKind.Object) { error = "action must be an object"; return null; }
        var kind = Str(a, "kind");
        if (kind == null || !KindLookup.TryGetValue(kind, out var type)) { error = $"unknown kind '{kind}'"; return null; }

        switch (type)
        {
            case CommandType.EndTurn:
                return new EndTurnCommand(pid);

            case CommandType.Move:
            {
                if (!Unit(a, gs, pid, out var unit, out error)) return null;
                if (!Coords(a, "to", gs, out var to, out error)) return null;
                return new MoveCommand(pid, unit, to);
            }
            case CommandType.Attack:
            {
                if (!Unit(a, gs, pid, out var unit, out error)) return null;
                if (!Coords(a, "target", gs, out var target, out error)) return null;
                return new AttackCommand(pid, unit, target);
            }
            case CommandType.Capture:
            {
                if (!Unit(a, gs, pid, out var unit, out error)) return null;
                return new CaptureCommand(pid, unit.id, unit.coordinates);
            }
            case CommandType.Train:
            {
                if (!Enum<UnitData.Type>(a, "unit_type", out var ut, out error)) return null;
                if (!Coords(a, "at", gs, out var at, out error)) return null;
                return new TrainCommand(pid, ut, at);
            }
            case CommandType.Upgrade:
            {
                if (!Enum<UnitData.Type>(a, "unit_type", out var ut, out error)) return null;
                if (!AtOrUnit(a, gs, pid, out var at, out error)) return null;
                return new UpgradeCommand(pid, ut, at);
            }
            case CommandType.Build:
            {
                if (!Enum<ImprovementData.Type>(a, "improvement", out var it, out error)) return null;
                if (!Coords(a, "at", gs, out var at, out error)) return null;
                return new BuildCommand(pid, it, at);
            }
            case CommandType.Research:
            {
                if (!Enum<TechData.Type>(a, "tech", out var tt, out error)) return null;
                return new ResearchCommand(pid, tt);
            }
            case CommandType.CityReward:
            {
                if (!Enum<CityReward>(a, "reward", out var reward, out error)) return null;
                if (!Coords(a, "at", gs, out var at, out error)) return null;
                return new CityRewardCommand(pid, reward, at);
            }
            case CommandType.PeaceRequestResponse:
            {
                if (!Byte(a, "opponent", out var opp, out error)) return null;
                if (!a.TryGetProperty("accept", out var acc) || (acc.ValueKind != JsonValueKind.True && acc.ValueKind != JsonValueKind.False))
                {
                    error = "'accept' must be true or false";
                    return null;
                }
                return new PeaceRequestResponseCommand(pid, opp, acc.GetBoolean());
            }
            case CommandType.PeaceTreaty:
            {
                if (!Byte(a, "opponent", out var opp, out error) || !Coords(a, "at", gs, out var at, out error)) return null;
                return new PeaceTreatyCommand(pid, opp, at);
            }
            case CommandType.EstablishEmbassy:
            {
                if (!Byte(a, "opponent", out var opp, out error) || !Coords(a, "at", gs, out var at, out error)) return null;
                return new EstablishEmbassyCommand(pid, opp, at);
            }
            case CommandType.DestroyEmbassy:
            {
                if (!Byte(a, "opponent", out var opp, out error) || !Coords(a, "at", gs, out var at, out error)) return null;
                return new DestroyEmbassyCommand(pid, opp, at);
            }
            case CommandType.BreakPeace:
            {
                if (!Byte(a, "opponent", out var opp, out error) || !Coords(a, "at", gs, out var at, out error)) return null;
                return new BreakPeaceCommand(pid, opp, at);
            }
            case CommandType.ClearTileEffect:
            {
                if (!Enum<TileData.EffectType>(a, "effect", out var effect, out error)) return null;
                if (!Coords(a, "at", gs, out var at, out error)) return null;
                return new ClearTileEffectCommand(pid, at, effect);
            }

            // player + one coordinate; given as "at" or implied by "unit_id"
            case CommandType.Recover: return AtOrUnit(a, gs, pid, out var c1, out error) ? new RecoverCommand(pid, c1) : null;
            case CommandType.HealOthers: return AtOrUnit(a, gs, pid, out var c2, out error) ? new HealOthersCommand(pid, c2) : null;
            case CommandType.Destroy: return AtOrUnit(a, gs, pid, out var c3, out error) ? new DestroyCommand(pid, c3) : null;
            case CommandType.Disband: return AtOrUnit(a, gs, pid, out var c4, out error) ? new DisbandCommand(pid, c4) : null;
            case CommandType.Promote: return AtOrUnit(a, gs, pid, out var c5, out error) ? new PromoteCommand(pid, c5) : null;
            case CommandType.ExamineRuins: return AtOrUnit(a, gs, pid, out var c6, out error) ? new ExamineRuinsCommand(pid, c6) : null;
            case CommandType.FreezeArea: return AtOrUnit(a, gs, pid, out var c7, out error) ? new FreezeAreaCommand(pid, c7) : null;
            case CommandType.BreakIce: return AtOrUnit(a, gs, pid, out var c8, out error) ? new BreakIceCommand(pid, c8) : null;
            case CommandType.Stay: return AtOrUnit(a, gs, pid, out var c9, out error) ? new StayCommand(pid, c9) : null;
            case CommandType.Explode: return AtOrUnit(a, gs, pid, out var c10, out error) ? new ExplodeCommand(pid, c10) : null;
            case CommandType.Boost: return AtOrUnit(a, gs, pid, out var c11, out error) ? new BoostCommand(pid, c11) : null;
            case CommandType.Decompose: return AtOrUnit(a, gs, pid, out var c12, out error) ? new DecomposeCommand(pid, c12) : null;
            case CommandType.Hide: return AtOrUnit(a, gs, pid, out var c13, out error) ? new HideCommand(pid, c13) : null;
            case CommandType.Disembark: return AtOrUnit(a, gs, pid, out var c14, out error) ? new DisembarkCommand(pid, c14) : null;
            case CommandType.Flood: return AtOrUnit(a, gs, pid, out var c15, out error) ? new FloodCommand(pid, c15) : null;
            case CommandType.Swarm: return AtOrUnit(a, gs, pid, out var c16, out error) ? new SwarmCommand(pid, c16) : null;

            default:
                error = $"'{kind}' cannot be sent through the bridge";
                return null;
        }
    }

    // ------------------------------------------------------------------ field helpers

    static string? Str(JsonElement a, string key) =>
        a.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    static bool Byte(JsonElement a, string key, out byte value, out string error)
    {
        value = 0; error = "";
        if (a.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var i) && i is >= 0 and <= 255)
        {
            value = (byte)i;
            return true;
        }
        error = $"'{key}' must be a player id (0-255)";
        return false;
    }

    static bool Enum<T>(JsonElement a, string key, out T value, out string error) where T : struct, System.Enum
    {
        value = default; error = "";
        var s = Str(a, key);
        if (s != null && System.Enum.TryParse(s, ignoreCase: true, out value)) return true;
        error = $"'{key}' must be one of {typeof(T).Name}: {string.Join(", ", System.Enum.GetNames<T>())}";
        return false;
    }

    /// <summary>Accepts [x, y] or {"x": .., "y": ..} and checks map bounds.</summary>
    static bool Coords(JsonElement a, string key, GameState gs, out WorldCoordinates coords, out string error)
    {
        coords = default; error = "";
        if (!a.TryGetProperty(key, out var v)) { error = $"missing '{key}' ([x, y])"; return false; }
        int x, y;
        if (v.ValueKind == JsonValueKind.Array && v.GetArrayLength() == 2 && v[0].TryGetInt32(out x) && v[1].TryGetInt32(out y)) { }
        else if (v.ValueKind == JsonValueKind.Object && v.TryGetProperty("x", out var xe) && v.TryGetProperty("y", out var ye)
                 && xe.TryGetInt32(out x) && ye.TryGetInt32(out y)) { }
        else { error = $"'{key}' must be [x, y]"; return false; }

        if (x < 0 || y < 0 || x >= gs.Map.Width || y >= gs.Map.Height) { error = $"'{key}' [{x}, {y}] is off the map"; return false; }
        coords = new WorldCoordinates(x, y);
        return true;
    }

    static bool Unit(JsonElement a, GameState gs, byte pid, out UnitState unit, out string error)
    {
        unit = null!; error = "";
        if (!a.TryGetProperty("unit_id", out var v) || v.ValueKind != JsonValueKind.Number || !v.TryGetUInt32(out var id))
        {
            error = "missing 'unit_id'";
            return false;
        }
        if (!gs.TryGetUnit(id, out unit) || unit == null) { error = $"unit {id} does not exist"; return false; }
        if (unit.owner != pid) { error = $"unit {id} is not yours"; return false; }
        return true;
    }

    static bool AtOrUnit(JsonElement a, GameState gs, byte pid, out WorldCoordinates at, out string error)
    {
        if (a.TryGetProperty("at", out _)) return Coords(a, "at", gs, out at, out error);
        if (Unit(a, gs, pid, out var unit, out error)) { at = unit.coordinates; return true; }
        at = default;
        error = "missing 'at' ([x, y]) or 'unit_id'";
        return false;
    }
}
