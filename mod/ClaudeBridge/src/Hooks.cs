using HarmonyLib;

namespace ClaudeBridge;

[HarmonyPatch]
internal static class Hooks
{
    /// <summary>
    /// GameManager is a MonoBehaviour that lives for the whole session, so its Update is the
    /// simplest reliable once-per-frame main-thread hook (same trick Polyfish uses).
    /// </summary>
    [HarmonyPatch(typeof(GameManager), "Update")]
    [HarmonyPostfix]
    static void GameManager_Update_Postfix() => Bridge.Tick();

    // Lifecycle tracing for the client's action loop, so it is visible in the log when and why
    // the "waiting for command" state is (not) reached after a load or a turn change.
    [HarmonyPatch(typeof(ClientActionManager), nameof(ClientActionManager.StartProcessing))]
    [HarmonyPostfix]
    static void AM_StartProcessing() => Bridge.Trace("ClientActionManager.StartProcessing");

    [HarmonyPatch(typeof(ClientActionManager), nameof(ClientActionManager.StopProcessing))]
    [HarmonyPostfix]
    static void AM_StopProcessing() => Bridge.Trace("ClientActionManager.StopProcessing");

    [HarmonyPatch(typeof(ClientActionManager), nameof(ClientActionManager.Pause))]
    [HarmonyPostfix]
    static void AM_Pause() => Bridge.Trace("ClientActionManager.Pause");

    [HarmonyPatch(typeof(ClientActionManager), nameof(ClientActionManager.Resume))]
    [HarmonyPostfix]
    static void AM_Resume() => Bridge.Trace("ClientActionManager.Resume");

    [HarmonyPatch(typeof(ClientActionManager), nameof(ClientActionManager.HoldExecution))]
    [HarmonyPostfix]
    static void AM_HoldExecution(bool value) => Bridge.Trace($"ClientActionManager.HoldExecution({value})");

    [HarmonyPatch(typeof(ClientActionManager), nameof(ClientActionManager.StartRecap))]
    [HarmonyPostfix]
    static void AM_StartRecap() => Bridge.Trace("ClientActionManager.StartRecap");

    [HarmonyPatch(typeof(ClientActionManager), nameof(ClientActionManager.EndRecap))]
    [HarmonyPostfix]
    static void AM_EndRecap() => Bridge.Trace("ClientActionManager.EndRecap");

    [HarmonyPatch(typeof(ClientBase), nameof(ClientBase.OnStartedProcessing))]
    [HarmonyPostfix]
    static void Client_OnStartedProcessing() => Bridge.Trace("ClientBase.OnStartedProcessing");

    [HarmonyPatch(typeof(ClientBase), nameof(ClientBase.OnFinishedProcessing))]
    [HarmonyPostfix]
    static void Client_OnFinishedProcessing() => Bridge.Trace("ClientBase.OnFinishedProcessing");

    [HarmonyPatch(typeof(ClientBase), nameof(ClientBase.SessionOpened))]
    [HarmonyPostfix]
    static void Client_SessionOpened() => Bridge.Trace("ClientBase.SessionOpened");

    [HarmonyPatch(typeof(ClientBase), nameof(ClientBase.PrepareSession))]
    [HarmonyPostfix]
    static void Client_PrepareSession() => Bridge.Trace("ClientBase.PrepareSession");

    [HarmonyPatch(typeof(ClientInteraction), nameof(ClientInteraction.OnTurnStarted))]
    [HarmonyPostfix]
    static void Interaction_OnTurnStarted() => Bridge.Trace("ClientInteraction.OnTurnStarted");
}
