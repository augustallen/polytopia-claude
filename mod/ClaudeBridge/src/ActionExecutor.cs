using System.Text.Json;
using PolytopiaBackendBase.Game;

namespace ClaudeBridge;

/// <summary>
/// JSON action -> CommandBase -> IsValid -> the client's normal command path, so the UI,
/// animations and save state stay consistent with what the engine did.
/// </summary>
internal static class ActionExecutor
{
    public static bool Execute(JsonElement action, out string? error, out string? kind)
    {
        kind = action.ValueKind == JsonValueKind.Object && action.TryGetProperty("kind", out var k) ? k.GetString() : null;

        var gs = GameManager.GameState;
        var client = GameManager.Client;
        if (gs == null || client == null) { error = "no game in progress"; return false; }
        if (gs.Settings.GameType != GameType.SinglePlayer) { error = "bridge only works in single-player games"; return false; }

        var me = GameManager.LocalPlayer;
        if (me == null) { error = "no local player"; return false; }
        if (gs.CurrentState != GameState.State.Started && gs.CurrentState != GameState.State.FinalTurn)
        {
            error = $"game is not running (state {gs.CurrentState})";
            return false;
        }
        if (gs.CurrentPlayer != me.Id || !client.IsPlayerLocal(gs.CurrentPlayer)) { error = "not your turn"; return false; }
        if (!Bridge.IsIdle(client))
        {
            error = "game is still processing the previous action";
            return false;
        }
        // Queued commands are held while a popup is up; refuse instead of silently queueing them,
        // unless the popup is the one asking for a choice the agent is about to make.
        bool triggerPending = gs.TryGetPendingCommandTrigger(me.Id, out var trigger) && trigger.type != CommandTriggerType.None;
        if (Bridge.IsPopupShowing() && !triggerPending)
        {
            error = "a popup is showing; wait for the next state";
            return false;
        }

        var cmd = CommandCodec.Decode(action, gs, me.Id, out var decodeError);
        if (cmd == null) { error = decodeError; return false; }

        if (!cmd.IsValid(gs, out var validationError))
        {
            error = string.IsNullOrEmpty(validationError) ? "command is not valid" : validationError;
            return false;
        }

        client.SendCommand(cmd);
        error = null;
        return true;
    }
}
