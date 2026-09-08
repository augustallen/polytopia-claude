using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using BepInEx.Logging;
using HarmonyLib;
using PolyMod.Api;
using Polytopia.Data;
using PolytopiaBackendBase.Game;

namespace ClaudeBridge;

/// <summary>
/// PolyMod entry point. PolyMod instantiates the first <see cref="PolyScript"/> subclass in the
/// assembly and calls <see cref="Load"/> during startup, before any game scene exists.
/// </summary>
public class ClaudeBridgePlugin : PolyScript
{
    public override void Load()
    {
        Bridge.Log = Logger;
        Bridge.LoadConfig();
        Harmony.CreateAndPatchAll(typeof(Hooks));
        // Keep ticking while the window is unfocused, otherwise the bridge stalls whenever the harness has focus.
        UnityEngine.Application.runInBackground = true;
        Bridge.StartServer();
        Logger.LogInfo($"ClaudeBridge {Mod.version} listening on {Bridge.BindAddress}:{Bridge.Port}");
    }

    public override void Unload() => Bridge.StopServer();
}

/// <summary>
/// Newline-delimited JSON over TCP. One agent at a time; a new connection replaces the old one.
/// Socket I/O happens on background threads, everything that touches the game happens in
/// <see cref="Tick"/>, which the <see cref="Hooks"/> patch runs once per frame on the Unity main thread.
/// </summary>
public static class Bridge
{
    public static ManualLogSource Log = null!;
    public static int Port = 9876;
    public static IPAddress BindAddress = IPAddress.Loopback;

    /// <summary>Frames the client must be idle before a state is sent, so gaps between chained actions are not mistaken for idleness.</summary>
    const int IdleFramesRequired = 5;
    const string ConnectedSentinel = "connected"; // cannot collide with a JSON line

    static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = false };
    static readonly object _writeLock = new();
    static readonly ConcurrentQueue<string> _inbox = new();
    static TcpListener? _listener;
    static TcpClient? _client;
    static StreamWriter? _writer;
    static volatile bool _connected;

    // Turn-watcher state (main thread only)
    static StateKey _lastSentKey = StateKey.None;
    static StateKey? _pendingKey;   // key at the time an accepted command was queued
    static float _pendingSince;
    const float PendingTimeoutSeconds = 5f;
    static bool _forceState;
    static bool _sentGameOver;
    static bool _warnedNotSinglePlayer;
    static bool _wasInGame;
    static int _idleFrames;
    static float _lastTickErrorLog;

    // Hotseat (Pass & Play) handoff state (main thread only)
    static byte _lastCurrentPlayer;
    static float _handoffSince = -1f;      // realtime when gs.CurrentPlayer last changed; -1 once a state was sent
    static float _lastHandoffWarning;
    static bool _handoffKicked;
    static int _overlaySeenId;
    static float _overlaySeenAt;
    static float _lastOverlayContinue;
    const float HandoffWarnSeconds = 10f;
    // The client only switches seats itself when the HUD's end-turn button drives the overlay; commands
    // sent through the bridge skip that path, so after the engine has moved on to the next player and
    // gone idle, the bridge makes the same call the overlay's Continue would.
    const float HandoffKickSeconds = 1.5f;

    // ------------------------------------------------------------------ config

    public static void LoadConfig()
    {
        var path = Path.Combine(BepInEx.Paths.ConfigPath, "ClaudeBridge.json");
        try
        {
            if (!File.Exists(path))
            {
                File.WriteAllText(path, "{\n  \"port\": 9876,\n  \"bind\": \"127.0.0.1\"\n}\n");
                return;
            }
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.TryGetProperty("port", out var p)) Port = p.GetInt32();
            if (doc.RootElement.TryGetProperty("bind", out var b) && b.GetString() is { } bind)
                BindAddress = bind == "0.0.0.0" ? IPAddress.Any : IPAddress.Parse(bind);
        }
        catch (Exception ex)
        {
            Log.LogWarning($"Could not read {path}: {ex.Message}; using defaults");
        }
    }

    // ------------------------------------------------------------------ server

    public static void StartServer()
    {
        _listener = new TcpListener(BindAddress, Port);
        _listener.Start();
        new Thread(AcceptLoop) { IsBackground = true, Name = "ClaudeBridge-accept" }.Start();
    }

    public static void StopServer()
    {
        try { _listener?.Stop(); } catch { /* shutting down */ }
        lock (_writeLock) DropClientLocked();
    }

    static void AcceptLoop()
    {
        while (true)
        {
            TcpClient client;
            try { client = _listener!.AcceptTcpClient(); }
            catch { break; } // listener stopped
            new Thread(() => ReadLoop(client)) { IsBackground = true, Name = "ClaudeBridge-read" }.Start();
        }
    }

    static void ReadLoop(TcpClient client)
    {
        StreamReader reader;
        lock (_writeLock)
        {
            DropClientLocked();
            client.NoDelay = true;
            var stream = client.GetStream();
            reader = new StreamReader(stream, new UTF8Encoding(false));
            _client = client;
            _writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };
            _connected = true;
        }
        Log.LogInfo($"Agent connected from {client.Client.RemoteEndPoint}");
        _inbox.Enqueue(ConnectedSentinel);
        try
        {
            string? line;
            while ((line = reader.ReadLine()) != null)
                if (line.Length > 0) _inbox.Enqueue(line);
        }
        catch (Exception ex) when (ex is IOException or ObjectDisposedException or SocketException) { }
        finally
        {
            lock (_writeLock)
            {
                if (_client == client) { _connected = false; _client = null; _writer = null; }
            }
            try { client.Close(); } catch { /* already closed */ }
            Log.LogInfo("Agent disconnected");
        }
    }

    static void DropClientLocked()
    {
        if (_client == null) return;
        try { _client.Close(); } catch { /* already closed */ }
        _client = null;
        _writer = null;
        _connected = false;
    }

    public static void Send(object message)
    {
        string json;
        try { json = JsonSerializer.Serialize(message, JsonOpts); }
        catch (Exception ex) { Log.LogError($"Serialize failed: {ex}"); return; }
        lock (_writeLock)
        {
            if (_writer == null) return;
            try { _writer.WriteLine(json); }
            catch (Exception ex)
            {
                Log.LogWarning($"Send failed: {ex.Message}");
                DropClientLocked();
            }
        }
    }

    // ------------------------------------------------------------------ main thread

    /// <summary>Called once per frame from the GameManager.Update postfix.</summary>
    public static void Tick()
    {
        try
        {
            while (_inbox.TryDequeue(out var line)) HandleLine(line);
            WatchGame();
        }
        catch (Exception ex)
        {
            // Throttled: a persistent failure here would otherwise flood the log every frame.
            if (UnityEngine.Time.realtimeSinceStartup - _lastTickErrorLog > 5f)
            {
                _lastTickErrorLog = UnityEngine.Time.realtimeSinceStartup;
                Log.LogError($"Tick failed: {ex}");
            }
        }
    }

    static void HandleLine(string line)
    {
        if (line == ConnectedSentinel)
        {
            ResetWatcher();
            Send(new
            {
                type = "hello",
                bridge_version = "0.1.0",
                game_version = UnityEngine.Application.version,
                in_game = GameManager.GameState != null,
            });
            return;
        }

        JsonDocument doc;
        try { doc = JsonDocument.Parse(line); }
        catch (JsonException ex)
        {
            Send(new { type = "error", error = $"bad json: {ex.Message}" });
            return;
        }

        using (doc)
        {
            var root = doc.RootElement;
            var type = root.TryGetProperty("type", out var t) ? t.GetString() : null;
            switch (type)
            {
                case "ping":
                    Send(new { type = "pong" });
                    break;

                case "get_state":
                    _forceState = true; // delivered by WatchGame once the client is idle
                    if (GameManager.GameState == null) Send(new { type = "error", error = "no game in progress" });
                    break;

                case "status":
                    Send(Status());
                    break;

                case "kick":
                {
                    // Diagnostics only: poke the client the way the UI would.
                    var client = GameManager.Client;
                    var method = root.TryGetProperty("method", out var m) ? m.GetString() : null;
                    if (client == null) { Send(new { type = "error", error = "no game" }); break; }
                    try
                    {
                        switch (method)
                        {
                            case "start_processing": client.ActionManager.StartProcessing(); break;
                            case "stop_processing": client.ActionManager.StopProcessing(); break;
                            case "resume_am": client.ActionManager.Resume(); break;
                            case "skip_recap": client.SkipRecap(); break;
                            case "force_update": client.ActionManager.ForceUpdate(); break;
                            case "end_recap": client.ActionManager.EndRecap(); break;
                            case "hold_off": client.ActionManager.HoldExecution(false); break;
                            case "finished_processing": client.OnFinishedProcessing(); break;
                            default: Send(new { type = "error", error = $"unknown kick method '{method}'" }); return;
                        }
                        Send(new { type = "ok", command = "kick", method });
                    }
                    catch (Exception ex)
                    {
                        Send(new { type = "error", error = $"kick {method} failed: {ex.Message}" });
                    }
                    break;
                }

                case "new_game":
                    // What the setup screen's Continue button does: fill PreliminaryGameSettings,
                    // pick the tribe, then CreateSinglePlayerGame (or CreateHotseatGame for an offline
                    // Pass & Play game with several human seats). Only from the start screen.
                    if (GameManager.GameState != null) { Send(new { type = "error", error = "already in a game; send return_to_menu first" }); break; }
                    try
                    {
                        var gameType = EnumArg(root, "game_type", GameType.SinglePlayer);
                        if (gameType != GameType.SinglePlayer && gameType != GameType.PassAndPlay)
                            throw new ArgumentException("'game_type' must be SinglePlayer or PassAndPlay (offline only)");
                        var mode = EnumArg(root, "mode", PolytopiaBackendBase.Game.GameMode.Perfection);
                        var difficulty = EnumArg(root, "difficulty", BotDifficulty.Easy);
                        var preset = EnumArg(root, "map_preset", MapPreset.Continents);
                        var tribe = EnumArg(root, "tribe", PolytopiaBackendBase.Common.TribeType.Imperius);
                        bool hotseat = gameType == GameType.PassAndPlay;
                        int humans = hotseat && root.TryGetProperty("players", out var hp) ? hp.GetInt32() : (hotseat ? 2 : 1);
                        int opponents = root.TryGetProperty("opponents", out var o) ? o.GetInt32()
                                      : root.TryGetProperty("bots", out var bp) ? bp.GetInt32() : (hotseat ? 0 : 3);
                        int mapSize = root.TryGetProperty("map_size", out var ms) ? ms.GetInt32()
                                    : GameSettings.GetPreferredMapSizeFromOpponentCount(hotseat ? humans - 1 + opponents : opponents);
                        var tribes = new List<PolytopiaBackendBase.Common.TribeType>();
                        if (root.TryGetProperty("tribes", out var tr) && tr.ValueKind == JsonValueKind.Array)
                            foreach (var e in tr.EnumerateArray())
                                tribes.Add(Enum.Parse<PolytopiaBackendBase.Common.TribeType>(e.GetString() ?? "", true));
                        while (tribes.Count < humans) tribes.Add(tribe);
                        if (hotseat && humans < 2) throw new ArgumentException("a pass-and-play game needs at least 2 'players'");

                        var settings = GameManager.PreliminaryGameSettings ?? new GameSettings();
                        if (hotseat)
                        {
                            try { settings.ApplyGameTypeDefaults(GameType.PassAndPlay, mode); }
                            catch (Exception ex) { Log.LogWarning($"ApplyGameTypeDefaults failed: {ex.Message}"); }
                        }
                        settings.GameType = gameType;
                        settings.BaseGameMode = mode;
                        settings.RulesGameMode = mode;
                        settings.rules = new GameRules(mode);
                        settings.mapPreset = preset;
                        settings.Difficulty = difficulty;
                        settings.OpponentCount = opponents;
                        settings.MapSize = mapSize;
                        settings.GameName = root.TryGetProperty("name", out var n) && n.GetString() is { } nm ? nm : $"claude {DateTime.Now:yyyyMMdd-HHmmss}";
                        if (hotseat)
                        {
                            // One PlayerData per human seat, the way the player picker + tribe picker fill them in.
                            HotseatProfilesState? profiles = null;
                            try { profiles = GameManager.GetHotseatProfilesState(); }
                            catch (Exception ex) { Log.LogWarning($"GetHotseatProfilesState failed: {ex.Message}"); }
                            settings.ClearPlayers();
                            for (int i = 0; i < humans; i++)
                            {
                                var pd = new PlayerData
                                {
                                    type = PlayerDataType.LocalUser,
                                    tribe = tribes[i],
                                    tribeMix = tribes[i],
                                    climate = tribes[i],
                                    skinType = PolytopiaBackendBase.Common.SkinType.Default,
                                    knownTribe = true,
                                    botDifficulty = difficulty,
                                    defaultName = $"Player {i + 1}",
                                };
                                try
                                {
                                    if (profiles?.players != null && i < profiles.players.Count) pd.profile = profiles.players[i];
                                }
                                catch (Exception ex) { Log.LogWarning($"profile {i}: {ex.Message}"); }
                                settings.AddPlayer(pd);
                            }
                            Log.LogInfo($"hotseat new_game: {humans} humans {opponents} bots mode {mode} map {mapSize} {preset} tribes [{string.Join(",", tribes)}] players={settings.GetPlayerCount()}");
                        }
                        GameManager.PreliminaryGameSettings = settings;
                        GameManager.SetStartingTribeValues(tribes[0], PolytopiaBackendBase.Common.SkinType.Default, tribes[0], tribes[0]);
                        if (hotseat) GameManager.Instance.CreateHotseatGame();
                        else GameManager.Instance.CreateSinglePlayerGame();
                        Send(new
                        {
                            type = "ok", command = "new_game", game_type = gameType.ToString(), mode = mode.ToString(),
                            difficulty = difficulty.ToString(), map_preset = preset.ToString(), tribe = tribes[0].ToString(),
                            tribes = tribes.ConvertAll(t => t.ToString()), players = humans, opponents, map_size = mapSize,
                        });
                    }
                    catch (Exception ex)
                    {
                        Log.LogError($"new_game failed: {ex}");
                        Send(new { type = "error", error = $"new_game failed: {ex.Message}" });
                    }
                    break;

                case "return_to_menu":
                    if (GameManager.GameState == null) { Send(new { type = "error", error = "not in a game" }); break; }
                    try { GameManager.ReturnToMenu(); Send(new { type = "ok", command = "return_to_menu" }); }
                    catch (Exception ex) { Send(new { type = "error", error = $"return_to_menu failed: {ex.Message}" }); }
                    break;

                case "resume":
                    // Same as the menu's Resume button; only meaningful from the start screen.
                    if (GameManager.GameState != null) { Send(new { type = "error", error = "already in a game" }); break; }
                    try
                    {
                        GameManager.Instance.ResumeSingleplayerGame();
                        Send(new { type = "ok", command = "resume" });
                    }
                    catch (Exception ex)
                    {
                        Send(new { type = "error", error = $"resume failed: {ex.Message}" });
                    }
                    break;

                case "action":
                    if (!root.TryGetProperty("action", out var action))
                    {
                        Send(new { type = "result", ok = false, error = "missing 'action'", kind = (string?)null });
                        break;
                    }
                    // Optional seat: in a hotseat game the harness says which player it is acting for,
                    // and the bridge refuses if that is not the seat currently at the keyboard.
                    byte? seat = root.TryGetProperty("player", out var pl) && pl.ValueKind == JsonValueKind.Number ? (byte)pl.GetInt32() : null;
                    var before = GameManager.GameState != null ? CurrentKey() : StateKey.None;
                    var ok = ActionExecutor.Execute(action, seat, out var error, out var kind);
                    Send(new { type = "result", ok, error, kind });
                    _idleFrames = 0;
                    if (ok)
                    {
                        // SendCommand usually only queues the command; hold the next state until the
                        // engine has actually consumed it (the command counter moves) so the harness
                        // never sees a stale state and re-sends the same action. When the action loop
                        // is stopped (after a resume, or a hotseat seat switch) the command is applied
                        // synchronously and the key has already moved: nothing to wait for then.
                        // CommandStack grows when the command is queued; CurrentCommand (and the turn or
                        // player) only move when the engine has applied it.
                        var after = GameManager.GameState != null ? CurrentKey() : StateKey.None;
                        bool consumed = after.Command != before.Command || after.Turn != before.Turn || after.Player != before.Player;
                        if (consumed)
                        {
                            _pendingKey = null;
                        }
                        else
                        {
                            _pendingKey = after;
                            _pendingSince = UnityEngine.Time.realtimeSinceStartup;
                        }
                    }
                    else
                    {
                        _forceState = true;
                    }
                    break;

                default:
                    Send(new { type = "error", error = $"unknown message type '{type}'" });
                    break;
            }
        }
    }

    public static void Trace(string what) => Log.LogInfo($"[trace] {what}");

    /// <summary>Case-insensitive enum argument with a default, e.g. "difficulty": "hard".</summary>
    static T EnumArg<T>(JsonElement root, string key, T fallback) where T : struct, Enum
    {
        if (root.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String && Enum.TryParse<T>(v.GetString(), true, out var parsed))
            return parsed;
        if (root.TryGetProperty(key, out v) && v.ValueKind == JsonValueKind.String)
            throw new ArgumentException($"'{key}' must be one of {string.Join(", ", Enum.GetNames<T>())}");
        return fallback;
    }

    // ------------------------------------------------------------------ game type / hotseat

    /// <summary>The bridge only ever acts in offline games: single-player, or Pass &amp; Play on this device.</summary>
    public static bool IsOfflineGame(GameSettings? settings)
    {
        if (settings == null) return false;
        var t = settings.GameType;
        return t == GameType.SinglePlayer || t == GameType.PassAndPlay;
    }

    public static bool IsHotseat(GameState gs) => gs.Settings != null && gs.Settings.GameType == GameType.PassAndPlay;

    /// <summary>The seat currently at the keyboard. In a hotseat game the client tracks it per turn.</summary>
    public static PlayerState? LocalSeat(GameState gs, ClientBase client)
    {
        PlayerState? fromClient = null;
        try { fromClient = client.GetCurrentLocalPlayer(); } catch (Exception) { }
        var fromManager = GameManager.LocalPlayer;
        if (IsHotseat(gs))
        {
            if (fromClient != null && fromClient.Id == gs.CurrentPlayer) return fromClient;
            if (fromManager != null && fromManager.Id == gs.CurrentPlayer) return fromManager;
        }
        return fromManager ?? fromClient;
    }

    static HotSeatOverlay? GetHotseatOverlay()
    {
        var ui = UIManager.Instance;
        if (ui == null) return null;
        IScreen? screen = null;
        try { screen = ui.GetScreen(UIConstants.Screens.HotSeatOverlay); } catch (Exception) { }
        return screen?.TryCast<HotSeatOverlay>();
    }

    static bool IsHotseatOverlayShowing()
    {
        var overlay = GetHotseatOverlay();
        return overlay != null && overlay.Showing;
    }

    /// <summary>
    /// The "pass the device to player N" screen between hotseat turns. Press Continue the way a tap
    /// would, after letting it settle. Returns true while it is showing.
    /// </summary>
    static bool HandleHotseatOverlay(GameState gs)
    {
        var overlay = GetHotseatOverlay();
        if (overlay == null || !overlay.Showing) { _overlaySeenId = 0; return false; }
        float now = UnityEngine.Time.realtimeSinceStartup;
        int id = overlay.GetInstanceID();
        if (id != _overlaySeenId) { _overlaySeenId = id; _overlaySeenAt = now; return true; }
        if (now - _overlaySeenAt < PopupSettleSeconds) return true;
        if (now - _lastOverlayContinue < 1.0f) return true;
        _lastOverlayContinue = now;
        Log.LogInfo($"Hotseat overlay showing (current player {gs.CurrentPlayer}, local {GameManager.LocalPlayer?.Id}); pressing Continue");
        try { overlay.ContinueClicked(); }
        catch (Exception ex) { Log.LogWarning($"HotSeatOverlay.ContinueClicked failed: {ex.Message}"); }
        return true;
    }

    /// <summary>
    /// Hotseat watchdog: the seat switch is the one step the bridge cannot see through the normal
    /// idle gate. After a stall it tries the client's own seat-switch call once, and reports every
    /// 10 s so the harness can give up instead of waiting forever.
    /// </summary>
    static bool _replayLogged;

    /// <summary>
    /// Hotseat recap: after the incoming seat's Continue the client rewinds to the start of the turn
    /// and replays the other seat's commands for them to watch (a few seconds). GameState is a rewound
    /// snapshot meanwhile, so the bridge just waits; SkipRecap is not used (it aborts the action loop).
    /// </summary>
    static bool HandleReplay(ClientBase client)
    {
        if (!IsReplaying(client)) { _replayLogged = false; return false; }
        if (!_replayLogged)
        {
            _replayLogged = true;
            Log.LogInfo("Hotseat recap in progress; waiting for it to finish");
        }
        return true;
    }

    static void HandoffWatchdog(GameState gs, ClientBase client, string where)
    {
        if (_handoffSince < 0) return;
        float now = UnityEngine.Time.realtimeSinceStartup;
        float stalled = now - _handoffSince;
        var local = GameManager.LocalPlayer;
        // Never touch the seat while the client is rewinding/replaying: CurrentPlayer is a snapshot then.
        bool settled = !IsReplaying(client) && (IsIdle(client) || stalled > HandoffWarnSeconds);
        if (stalled > HandoffKickSeconds && settled && !_handoffKicked && (local == null || local.Id != gs.CurrentPlayer) && !IsHotseatOverlayShowing())
        {
            _handoffKicked = true;
            Log.LogWarning($"Hotseat handoff stalled {stalled:F0}s at '{where}' (local {local?.Id}, current {gs.CurrentPlayer}); calling SetNewLocalPlayerTurnForPassAndPlay({gs.CurrentPlayer})");
            try { client.SetNewLocalPlayerTurnForPassAndPlay(gs.CurrentPlayer); }
            catch (Exception ex) { Log.LogWarning($"SetNewLocalPlayerTurnForPassAndPlay failed: {ex.Message}"); }
        }
        if (stalled > HandoffWarnSeconds && now - _lastHandoffWarning > HandoffWarnSeconds)
        {
            _lastHandoffWarning = now;
            var status = Status();
            status["type"] = "warning";
            status["reason"] = "handoff stalled";
            status["where"] = where;
            status["stalled_seconds"] = Math.Round(stalled);
            Log.LogWarning($"Hotseat handoff stalled {stalled:F0}s at '{where}': {JsonSerializer.Serialize(status, JsonOpts)}");
            Send(status);
        }
    }

    static float _lastPopupDismiss;
    static int _popupSeenId;
    static float _popupSeenAt;
    const float PopupSettleSeconds = 1.0f;

    public static bool IsPopupShowing()
    {
        var popup = PopupManager.GetCurrentPopup();
        return popup != null && popup.IsShowing();
    }

    /// <summary>
    /// Closes the current popup the way a tap would, if any. Returns true if one was showing.
    /// Skippable popups are hidden; unskippable ones ("You got a new task!") get their default
    /// button pressed. Nothing is touched while a command trigger (city reward, peace request) is
    /// pending for us: that choice belongs to the agent and is answered with a command.
    /// </summary>
    static bool DismissPopup(GameState gs, byte pid)
    {
        var popup = PopupManager.GetCurrentPopup();
        if (popup == null || !popup.IsShowing()) { _popupSeenId = 0; return false; }
        if (gs.TryGetPendingCommandTrigger(pid, out var trigger) && trigger.type != CommandTriggerType.None) return false;

        // Let a popup finish appearing before touching it: some spawn content in coroutines
        // ("You meet <tribe>" builds its tribe-info link a few frames in) and closing them early
        // dereferences destroyed components, which the game treats as a crash and quits on.
        float now = UnityEngine.Time.realtimeSinceStartup;
        int id = popup.GetInstanceID();
        if (id != _popupSeenId) { _popupSeenId = id; _popupSeenAt = now; return true; }
        if (now - _popupSeenAt < PopupSettleSeconds) return true;
        // One dismissal per half second: hiding animates, and a spam of Hide calls confuses the scroller.
        if (now - _lastPopupDismiss < 0.5f) return true;
        _lastPopupDismiss = now;

        string what = $"{popup.GetType().Name} id='{popup.identifier}' header='{popup.Header}'";
        if (!popup.IsUnskippable)
        {
            Log.LogInfo($"Hiding popup {what}");
            PopupManager.HideCurrentPopup();
            return true;
        }
        if (PressDefaultButton(popup)) Log.LogInfo($"Pressed default button of popup {what}");
        else Log.LogWarning($"Unskippable popup with no button to press: {what}");
        return true;
    }

    /// <summary>Simulates a click on the popup's default selectable (Polyfish's ClickButton recipe).</summary>
    static bool PressDefaultButton(PopupBase popup)
    {
        var selectable = popup.DefaultSelectable ?? popup.CurrentSelectable;
        UnityEngine.GameObject? target = selectable != null ? selectable.gameObject : null;
        if (target == null)
        {
            // Popups mix UI generations (UIButtonBase, UIButtonBase_UI2 and their subclasses).
            // Inline tribe-info link buttons (TribeInfoButton) are skipped. Last one = primary/OK.
            foreach (var component in popup.GetComponentsInChildren<UnityEngine.Component>(true))
            {
                if (component == null || !component.gameObject.activeInHierarchy) continue;
                bool isButton = component.TryCast<UIButtonBase_UI2>() != null || component.TryCast<UIButtonBase>() != null;
                if (!isButton || component.GetIl2CppType().Name.Contains("Info")) continue;
                target = component.gameObject;
            }
        }
        if (target == null)
        {
            Log.LogInfo($"No button found in popup '{popup.Header}'; hiding it directly");
            popup.Hide();
            return true;
        }

        var eventSystem = UnityEngine.EventSystems.EventSystem.current;
        var data = new UnityEngine.EventSystems.PointerEventData(eventSystem)
        {
            button = UnityEngine.EventSystems.PointerEventData.InputButton.Left,
        };
        eventSystem?.SetSelectedGameObject(target);
        // ExecuteHierarchy bubbles up to the nearest handler, so hitting a button's child (icon, label) still works.
        UnityEngine.EventSystems.ExecuteEvents.ExecuteHierarchy(target, data, UnityEngine.EventSystems.ExecuteEvents.pointerDownHandler);
        UnityEngine.EventSystems.ExecuteEvents.ExecuteHierarchy(target, data, UnityEngine.EventSystems.ExecuteEvents.pointerUpHandler);
        UnityEngine.EventSystems.ExecuteEvents.ExecuteHierarchy(target, data, UnityEngine.EventSystems.ExecuteEvents.pointerClickHandler);
        return true;
    }

    public static bool IsIdle(ClientBase client)
    {
        if (client.isWaitingForServer) return false;
        var am = client.ActionManager;
        if (am == null) return false;
        if (am.IsPausedOrPausing) return false;
        if (IsReplaying(client)) return false;
        return client.IsWaitingForCommand || !am.IsProcessing;
    }

    /// <summary>
    /// The client is rewinding/replaying commands (a hotseat recap of the previous seat's turn, or a
    /// replay): GameState is a rewound snapshot, so nothing it says can be trusted until this ends.
    /// </summary>
    public static bool IsReplaying(ClientBase client)
    {
        // IsRecap / ActionManager.isRecapping stay true for a whole human turn in a hotseat game, so they
        // say nothing; the target state exists exactly from "Rewinding to command 0" until the replay
        // has caught up with it.
        try { return client.IsReplay || client.HasTargetState(); }
        catch (Exception) { return false; }
    }

    /// <summary>Anything that changes when the engine consumes a command, the turn moves on, or (hotseat) the seat changes.</summary>
    record struct StateKey(uint Turn, ushort Command, int Stack, int Triggers, byte Player)
    {
        public static readonly StateKey None = new(0, 0, -1, -1, 255);
    }

    static StateKey CurrentKey()
    {
        var gs = GameManager.GameState;
        return new StateKey(gs.CurrentTurn, gs.CurrentCommand, gs.CommandStack?.Count ?? 0, gs.pendingCommandTriggers?.Count ?? 0, gs.CurrentPlayer);
    }

    /// <summary>Every input the turn watcher looks at, for debugging why no state is being sent.</summary>
    static Dictionary<string, object?> Status()
    {
        var d = new Dictionary<string, object?> { ["type"] = "status", ["connected"] = _connected, ["idle_frames"] = _idleFrames };
        try
        {
            var gm = GameManager.Instance;
            var gs = GameManager.GameState;
            var client = GameManager.Client;
            d["has_game_manager"] = gm != null;
            d["is_level_loaded"] = gm?.isLevelLoaded;
            d["is_loading_game"] = gm?.isLoadingGame;
            d["has_game_state"] = gs != null;
            d["has_client"] = client != null;
            if (gs != null)
            {
                d["game_type"] = gs.Settings?.GameType.ToString();
                d["current_state"] = gs.CurrentState.ToString();
                d["turn"] = gs.CurrentTurn;
                d["current_player"] = gs.CurrentPlayer;
                d["current_command"] = gs.CurrentCommand;
                d["pending_triggers"] = gs.pendingCommandTriggers?.Count;
                d["local_player"] = GameManager.LocalPlayer?.Id;
                d["is_hotseat"] = IsHotseat(gs);
                d["roster"] = StateSerializer.Roster(gs);
                d["command_stack"] = gs.CommandStack?.Count;
                d["pending_key"] = _pendingKey?.ToString();
                d["last_sent_key"] = _lastSentKey.ToString();
                d["handoff_stalled_seconds"] = _handoffSince >= 0 ? Math.Round(UnityEngine.Time.realtimeSinceStartup - _handoffSince) : (double?)null;
            }
            try
            {
                var ui = UIManager.Instance;
                d["ui_screen"] = ui?.CurrentScreen.ToString();
                d["hotseat_overlay_showing"] = IsHotseatOverlayShowing();
            }
            catch (Exception ex) { d["ui_error"] = ex.Message; }
            if (client != null)
            {
                d["client_type"] = client.GetType().Name;
                if (gs != null) d["is_local_turn"] = client.IsPlayerLocal(gs.CurrentPlayer);
                try
                {
                    d["client_local_player"] = client.GetCurrentLocalPlayer()?.Id;
                    d["current_local_player_index"] = client.currentLocalPlayerIndex;
                }
                catch (Exception ex) { d["client_local_error"] = ex.Message; }
                d["has_action_manager"] = client.ActionManager != null;
                d["is_processing"] = client.ActionManager?.IsProcessing;
                d["has_queued_actions"] = client.HasQueuedActions();
                d["is_waiting_for_server"] = client.isWaitingForServer;
                d["is_waiting_for_command"] = client.IsWaitingForCommand;
                d["is_ready"] = client.IsReady;
                d["is_recap"] = client.IsRecap;
                d["is_replay"] = client.IsReplay;
                d["is_replaying"] = IsReplaying(client);
                d["has_target_state"] = client.HasTargetState();
                d["gm_is_paused"] = gm?.isPaused;
                var popup = PopupManager.GetCurrentPopup();
                d["popup"] = popup != null && popup.IsShowing() ? $"{popup.GetType().Name} '{popup.name}'" : null;
                d["popup_unskippable"] = PopupManager.IsUnskippablePopupShowing();
                var am = client.ActionManager;
                if (am != null)
                {
                    d["am_is_paused"] = am.IsPaused;
                    d["am_is_paused_or_pausing"] = am.IsPausedOrPausing;
                    d["am_is_simulating"] = am.IsSimulating;
                    d["am_is_reacting"] = am.isReacting;
                    d["am_is_holding"] = am.isHolding;
                    d["am_is_recapping"] = am.isRecapping;
                    d["am_last_seen_command"] = am.LastSeenCommand;
                }
            }
        }
        catch (Exception ex)
        {
            d["error"] = ex.ToString();
        }
        return d;
    }

    static void ResetWatcher()
    {
        _lastSentKey = StateKey.None;
        _pendingKey = null;
        _forceState = false;
        _sentGameOver = false;
        _warnedNotSinglePlayer = false;
        _idleFrames = 0;
        _handoffSince = -1f;
        _handoffKicked = false;
        _lastCurrentPlayer = 255;
        _overlaySeenId = 0;
    }

    static void WatchGame()
    {
        if (!_connected) return;

        var gs = GameManager.GameState;
        var client = GameManager.Client;
        var gm = GameManager.Instance;
        if (gs == null || client == null || gm == null || !gm.isLevelLoaded || gm.isLoadingGame)
        {
            if (_wasInGame)
            {
                _wasInGame = false;
                ResetWatcher();
                Send(new { type = "left_game" });
            }
            return;
        }

        // Safety guard: the bridge never touches anything but offline games (single-player, or Pass & Play on this device).
        if (!IsOfflineGame(gs.Settings))
        {
            if (!_warnedNotSinglePlayer)
            {
                _warnedNotSinglePlayer = true;
                Log.LogWarning($"Game type is {gs.Settings.GameType}; bridge stays inert.");
                Send(new { type = "error", error = $"bridge only works in offline single-player or pass-and-play games (this is {gs.Settings.GameType})" });
            }
            return;
        }

        if (!_wasInGame)
        {
            _wasInGame = true;
            ResetWatcher();
            Log.LogInfo("Entered game: " + JsonSerializer.Serialize(Status(), JsonOpts));
        }

        if (gs.CurrentState == GameState.State.Ended)
        {
            if (!_sentGameOver)
            {
                _sentGameOver = true;
                Send(StateSerializer.BuildGameOverMessage(gs, client));
            }
            return;
        }
        bool hotseat = IsHotseat(gs);
        if (hotseat)
        {
            if (gs.CurrentPlayer != _lastCurrentPlayer)
            {
                _lastCurrentPlayer = gs.CurrentPlayer;
                _handoffSince = UnityEngine.Time.realtimeSinceStartup;
                _handoffKicked = false;
            }
            // "Pass the device to player N": press Continue, then wait for the seat switch to land.
            // This comes before the running-state gate because the very first overlay is what starts
            // the game (CurrentState stays Unknown until player 1 taps it).
            if (HandleHotseatOverlay(gs)) { _idleFrames = 0; HandoffWatchdog(gs, client, "overlay"); return; }
        }

        if (gs.CurrentState != GameState.State.Started && gs.CurrentState != GameState.State.FinalTurn)
        {
            if (hotseat) HandoffWatchdog(gs, client, $"state {gs.CurrentState}");
            return;
        }

        // Informational popups ("You got a new technology!", tribe met, task unlocked, ...) hold
        // every queued command - including the bots' turns - until closed, so close them the way a
        // tap would, whoever's turn it is. The pending-trigger guard is checked for the seat whose
        // turn it is (in a hotseat game that is not necessarily GameManager.LocalPlayer yet).
        var local = GameManager.LocalPlayer;
        byte popupPid = hotseat ? gs.CurrentPlayer : (local != null ? local.Id : gs.CurrentPlayer);
        if (DismissPopup(gs, popupPid)) { _idleFrames = 0; if (hotseat) HandoffWatchdog(gs, client, "popup"); return; }

        // The recap that follows a hotseat overlay rewinds GameState; wait it out (popups first: one could hold it).
        if (hotseat && HandleReplay(client)) { _idleFrames = 0; HandoffWatchdog(gs, client, "recap"); return; }

        if (!client.IsPlayerLocal(gs.CurrentPlayer)) { _idleFrames = 0; if (hotseat) HandoffWatchdog(gs, client, "not local"); return; }
        if (hotseat)
        {
            // Both the manager's and the client's idea of the local seat must be the current player.
            var seat = LocalSeat(gs, client);
            var manager = GameManager.LocalPlayer;
            if (seat == null || seat.Id != gs.CurrentPlayer || manager == null || manager.Id != gs.CurrentPlayer)
            {
                _idleFrames = 0;
                HandoffWatchdog(gs, client, "seat mismatch");
                return;
            }
        }

        // "Your move" has two shapes: the action loop is running and waiting for a command (fresh
        // game / after a turn change), or the loop is stopped altogether (after a mid-game resume,
        // until the first command starts it again). IsProcessing/HasQueuedActions alone are useless
        // because they stay true for the whole human turn in the first shape.
        bool idle = IsIdle(client);
        if (!idle) { _idleFrames = 0; return; }
        if (++_idleFrames < IdleFramesRequired) return;

        var key = CurrentKey();
        if (_pendingKey is { } pending)
        {
            if (key != pending) _pendingKey = null;
            else if (UnityEngine.Time.realtimeSinceStartup - _pendingSince > PendingTimeoutSeconds)
            {
                Log.LogWarning($"Accepted command was not consumed by the engine within 5s; resending state (key at accept {pending}, now {key}, waiting_for_command {client.IsWaitingForCommand}, processing {client.ActionManager?.IsProcessing})");
                _pendingKey = null;
                _forceState = true;
            }
            else return;
        }
        if (!_forceState && key == _lastSentKey) return;
        _forceState = false;
        _lastSentKey = key;
        _handoffSince = -1f;
        Send(StateSerializer.BuildStateMessage(gs, client));
    }
}
