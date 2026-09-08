# Windows setup (Phase 0)

Everything below was done on 2026-09-05 and is what the mod build in `mod/ClaudeBridge` assumes.

## Versions pinned

| Component | Version | Where it came from |
|---|---|---|
| The Battle of Polytopia (Steam app 874390) | `2.17.2.16299` (Steam buildid `24051203`, game logic data v28, Unity `6000.3.17f1`) | `<game>/version.txt`, `steamapps/appmanifest_874390.acf`, `BepInEx/LogOutput.log` |
| BepInEx | `6.0.0-be.785+6abdba4` (Unity.IL2CPP, win-x64) | `https://polymod.dev/data/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.785%2B6abdba4.zip` (URL published at `https://polymod.dev/data/bepinex.txt`) — sha256 `9ccf5d904b37c6635b9380c70ebe44b36e34b2d7f58d2f7d6a52f78ee27f009a` |
| PolyMod | `v1.2.17` (2026-07-06) | `https://github.com/PolyModdingTeam/PolyMod/releases/download/v1.2.17/PolyMod.dll` — sha256 `8a0cb13f1226dc94bddcf2a488921d057f60a93d1734c2e52835bfa3d39c1194` |
| .NET SDK | `6.0.428` | `winget install --id Microsoft.DotNet.SDK.6 --exact` |
| Git | `2.55.0.windows.3` | already installed |

Game directory (`<game>` below):
`C:\Program Files (x86)\Steam\steamapps\common\The Battle of Polytopia`

## Steps

1. Install the game from Steam and launch it once unmodded.
2. Install the .NET 6 SDK:
   ```powershell
   winget install --id Microsoft.DotNet.SDK.6 --exact --silent --accept-source-agreements --accept-package-agreements
   & "C:\Program Files\dotnet\dotnet.exe" --list-sdks   # 6.0.428
   ```
3. Install BepInEx + PolyMod. This is exactly what `installer/main.py` in the PolyMod repo does, without the GUI:
   ```bash
   G="/c/Program Files (x86)/Steam/steamapps/common/The Battle of Polytopia"
   curl -sL -o bepinex.zip "https://polymod.dev/data/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.785%2B6abdba4.zip"
   curl -sL -o PolyMod.dll "https://github.com/PolyModdingTeam/PolyMod/releases/download/v1.2.17/PolyMod.dll"
   unzip -q -o bepinex.zip -d "$G"          # adds BepInEx/, dotnet/, winhttp.dll, doorstop_config.ini, changelog.txt
   mkdir -p "$G/BepInEx/plugins"
   cp PolyMod.dll "$G/BepInEx/plugins/"
   ```
4. Launch the game once through Steam (`start steam://rungameid/874390`). The first boot runs Cpp2IL + Il2CppInterop (~30 s) and generates `BepInEx/interop/*.dll` — the assemblies our `.csproj` references. It also creates `<game>/Mods/`, `<game>/PolyMod.json`, and `<game>/CHECKSUM`.
5. Sanity-check a catalogue mod (done with *Freedom of Choice* v1.2.1, id `freedomofchoice`, which ships a DLL plus data patches, no dependencies):
   ```bash
   curl -sL -o "$G/Mods/freedomofchoice.polymod" "https://polymod.dev/api/mods/freedomofchoice/download"
   # relaunch, confirm the log lines below, then delete the file again
   ```

## Verify

Log file is `<game>/BepInEx/LogOutput.log` (not `.txt`). A good boot contains:

```
[Message: Preloader] BepInEx 6.0.0-be.785 - Polytopia
[Info   :   BepInEx] Loading [PolyMod 1.2.17]
[Message:   BepInEx] Chainloader startup complete
[Info   :   PolyMod] Loaded all mods in 122ms
```

With the test mod installed, the same log additionally showed (this is the exact lifecycle our plugin will go through):

```
[Info   :   PolyMod] Registered mod freedomofchoice
[Message:PolyMod] [freedomofchoice] City Rewards dll loaded.
[Info   :   PolyMod] Invoked Load method with logger from focmod.Main from freedomofchoice mod
[Info   :   PolyMod] Registered sprite data from freedomofchoice mod
[Info   :   PolyMod] Registered localization from freedomofchoice mod
[Info   :   PolyMod] Registered patch from freedomofchoice mod
[Info   :   PolyMod] Loaded all mods in 563ms
```

`ErrorLog.log` next to it only contains Steam breakpad lines; that is normal.

## Mod container format (from PolyMod `src/Loader.cs`)

PolyMod scans `<game>/Mods/` for directories, `*.polymod` and `*.zip`. Each must contain a `manifest.json`:

```json
{ "id": "claudebridge", "name": "Claude Bridge", "description": "...", "version": "0.1.0", "authors": ["..."] }
```

`id` must match `^(?!polytopia$)[a-z_]+$`. Optional `dependencies: [{id, min, max, required}]` and `client: true`. Any `.dll` in the container is loaded and PolyMod invokes its `Load` entry point (see `src/Api/PolyScript.cs`).

## Building and running the bridge mod

```powershell
cd mod\ClaudeBridge
& "C:\Program Files\dotnet\dotnet.exe" build -c Release     # -p:GamePath=... if Steam is elsewhere
```

The post-build step zips `ClaudeBridge.dll` + `manifest.json` into `<game>\Mods\ClaudeBridge.polymod`.
The game must be **restarted** to pick up a new build (PolyMod loads mod DLLs once at startup). On boot the
log should show:

```
[Info   :   PolyMod] Registered mod claudebridge
[Info   :PolyMod] [claudebridge] ClaudeBridge 0.1.0 listening on 127.0.0.1:9876
```

Config lives in `<game>\BepInEx\config\ClaudeBridge.json` (created on first run). The bridge only acts in
offline games (single-player, or Pass & Play with two human seats for the deathmatch); start one by hand from
the game's menu or with `new_game`, then run the harness. Protocol: `docs/PROTOCOL.md`.

Looking up game API surface (there is no decompiled source on the box): `dotnet tool install -g ilspycmd --version 8.2.0.7535`
(the current ilspycmd needs .NET 10) and e.g. `ilspycmd -t GameManager "<game>\BepInEx\interop\PolytopiaAssembly.dll"`,
or `ilspycmd -p -o <dir> <dll>` to dump every type for grepping. The interop stubs carry signatures, fields and enum values,
not method bodies. The game updated itself to 2.17.3.16375 on 2026-09-07; the mod built against the regenerated interop
DLLs without changes.

Python: the winget installer for Python 3.12 hung on this machine, so a portable CPython 3.12.10 (the NuGet
`python` package, full stdlib + pip) lives at `%USERPROFILE%\tools\python312\tools\python.exe`; a portable
Node 22 (+ the Codex CLI) at `%USERPROFILE%\tools\node`. Both are on the user PATH (new shells only).

Unattended smoke test — restarts nothing, resumes the saved game itself and plays random legal actions:

```powershell
python harness\scripts\smoke.py --resume --policy random --turns 10
python harness\scripts\bridgectl.py status            # why is no state being sent?
python harness\scripts\bridgectl.py resume --wait 12 get_state
```

Restarting the game from a script: kill `Polytopia.exe`, `start steam://rungameid/874390`, wait for
`StartScreen.Init` + `Connected to backend` in the log, then send `resume` or `new_game`
(`polytopia_bridge.runner.restart_game` does exactly this).

Playing and evaluating (needs `ANTHROPIC_API_KEY` for the Claude agent; `cd harness` first):

```powershell
python -m pytest -q                                                    # offline tests
python scripts\play_game.py --new --agent random --opponents 1 --map-size 11 --max-turns 5
python scripts\play_game.py --new --model claude-fable-5-1 --effort medium
python scripts\run_eval.py --games 5 --difficulties Easy,Normal --agents random,claude:claude-fable-5-1
```

## Keeping the build reproducible

- Steam: right-click the game → Properties → Updates → "Only update this game when I launch it". (`AutoUpdateBehavior` in `appmanifest_874390.acf` is currently `0` = always keep updated.)
- PolyMod self-updates by default (`<game>/PolyMod.json` has `"autoUpdate": true`). Set it to `false` once the bridge is working so the loader version stays pinned.
- If the game updates, delete `BepInEx/interop/` and `BepInEx/cache/` and launch once to regenerate; then rebuild the mod against the new DLLs and diff the lists below.

## Uninstall

Delete `<game>/BepInEx`, `<game>/dotnet`, `<game>/Mods`, and the files `winhttp.dll`, `doorstop_config.ini`, `changelog.txt`, `.doorstop_version`, `PolyMod.json`, `CHECKSUM` (mirrors the installer's `uninstall()`).

## `BepInEx/core/` (37 files)

```
0Harmony.dll
AsmResolver.DotNet.dll
AsmResolver.PE.File.dll
AsmResolver.PE.dll
AsmResolver.dll
AssetRipper.CIL.dll
AssetRipper.Primitives.dll
BepInEx.Core.dll
BepInEx.Core.xml
BepInEx.Preloader.Core.dll
BepInEx.Preloader.Core.xml
BepInEx.Unity.Common.dll
BepInEx.Unity.Common.xml
BepInEx.Unity.IL2CPP.dll
BepInEx.Unity.IL2CPP.dll.config
BepInEx.Unity.IL2CPP.xml
Cpp2IL.Core.dll
Disarm.dll
Gee.External.Capstone.dll
Iced.dll
Il2CppInterop.Common.dll
Il2CppInterop.Generator.dll
Il2CppInterop.HarmonySupport.dll
Il2CppInterop.Runtime.dll
LibCpp2IL.dll
Mono.Cecil.Mdb.dll
Mono.Cecil.Pdb.dll
Mono.Cecil.Rocks.dll
Mono.Cecil.dll
MonoMod.Backports.dll
MonoMod.ILHelpers.dll
MonoMod.RuntimeDetour.dll
MonoMod.Utils.dll
SemanticVersioning.dll
StableNameDotNet.dll
WasmDisassembler.dll
dobby.dll
```

## `BepInEx/interop/` (180 files, generated on first launch for game 2.17.2.16299)

Game-specific assemblies we care about: `GameLogicAssembly.dll` (namespace `Polytopia.Data`: rules engine, commands), `PolytopiaAssembly.dll` (Unity client: `GameManager`, UI), `PolytopiaBackendBase.dll`, `Newtonsoft.Json.dll`.

```
DOTween.dll
DebugLogger.dll
DebugOverlay.dll
Enums.NET.dll
Facepunch.Steamworks.Win64.dll
GameLogicAssembly.dll
I2Localization.dll
IchiGamepad.dll
Il2CppMicrosoft.AspNetCore.Connections.Abstractions.dll
Il2CppMicrosoft.AspNetCore.Http.Connections.Client.dll
Il2CppMicrosoft.AspNetCore.Http.Connections.Common.dll
Il2CppMicrosoft.AspNetCore.Http.Features.dll
Il2CppMicrosoft.AspNetCore.SignalR.Client.Core.dll
Il2CppMicrosoft.AspNetCore.SignalR.Client.dll
Il2CppMicrosoft.AspNetCore.SignalR.Common.dll
Il2CppMicrosoft.AspNetCore.SignalR.Protocols.Json.dll
Il2CppMicrosoft.Bcl.AsyncInterfaces.dll
Il2CppMicrosoft.Extensions.Configuration.Abstractions.dll
Il2CppMicrosoft.Extensions.Configuration.Binder.dll
Il2CppMicrosoft.Extensions.Configuration.dll
Il2CppMicrosoft.Extensions.DependencyInjection.Abstractions.dll
Il2CppMicrosoft.Extensions.DependencyInjection.dll
Il2CppMicrosoft.Extensions.Logging.Abstractions.dll
Il2CppMicrosoft.Extensions.Logging.Configuration.dll
Il2CppMicrosoft.Extensions.Logging.Console.dll
Il2CppMicrosoft.Extensions.Logging.dll
Il2CppMicrosoft.Extensions.Options.ConfigurationExtensions.dll
Il2CppMicrosoft.Extensions.Options.dll
Il2CppMicrosoft.Extensions.Primitives.dll
Il2CppMono.Security.dll
Il2CppSystem.Buffers.dll
Il2CppSystem.ComponentModel.Annotations.dll
Il2CppSystem.ComponentModel.DataAnnotations.dll
Il2CppSystem.Configuration.dll
Il2CppSystem.Core.dll
Il2CppSystem.Data.dll
Il2CppSystem.Drawing.dll
Il2CppSystem.IO.Pipelines.dll
Il2CppSystem.Memory.dll
Il2CppSystem.Net.Http.dll
Il2CppSystem.Numerics.Vectors.dll
Il2CppSystem.Numerics.dll
Il2CppSystem.Runtime.CompilerServices.Unsafe.dll
Il2CppSystem.Runtime.Serialization.dll
Il2CppSystem.Text.Encodings.Web.dll
Il2CppSystem.Text.Json.dll
Il2CppSystem.Threading.Channels.dll
Il2CppSystem.Threading.Tasks.Extensions.dll
Il2CppSystem.ValueTuple.dll
Il2CppSystem.Xml.Linq.dll
Il2CppSystem.Xml.dll
Il2CppSystem.dll
Il2Cppmscorlib.dll
K4os.Compression.LZ4.dll
MethodAddressToToken.db
MethodXrefScanCache.db
NativeShare.Runtime.dll
NaughtyAttributes.Core.dll
NaughtyAttributes.Test.dll
Newtonsoft.Json.dll
NintendoSDK.dll
PolytopiaAssembly.dll
PolytopiaBackendBase.dll
SignalRNewtonsoftAotProtocol.dll
Unity.Addressables.dll
Unity.Burst.Unsafe.dll
Unity.Burst.dll
Unity.Collections.dll
Unity.InputSystem.ForUI.dll
Unity.InputSystem.dll
Unity.InternalAPIEngineBridge.004.dll
Unity.Mathematics.dll
Unity.MemoryProfiler.dll
Unity.Purchasing.AppleMacosStub.dll
Unity.Purchasing.AppleStub.dll
Unity.Purchasing.SecurityCore.dll
Unity.Purchasing.SecurityStub.dll
Unity.Purchasing.Stores.dll
Unity.Purchasing.Utilities.dll
Unity.Purchasing.dll
Unity.RenderPipeline.Universal.ShaderLibrary.dll
Unity.RenderPipelines.Core.Runtime.Shared.dll
Unity.RenderPipelines.Core.Runtime.dll
Unity.RenderPipelines.GPUDriven.Runtime.dll
Unity.RenderPipelines.Universal.Runtime.dll
Unity.ResourceManager.dll
Unity.Services.Analytics.dll
Unity.Services.Core.Configuration.dll
Unity.Services.Core.Device.dll
Unity.Services.Core.Environments.Internal.dll
Unity.Services.Core.Internal.dll
Unity.Services.Core.Registration.dll
Unity.Services.Core.Scheduler.dll
Unity.Services.Core.Telemetry.dll
Unity.Services.Core.Threading.dll
Unity.Services.Core.dll
Unity.TextMeshPro.dll
Unity.UnifiedRayTracing.Runtime.dll
UnityEngine.AIModule.dll
UnityEngine.AccessibilityModule.dll
UnityEngine.AdaptivePerformanceModule.dll
UnityEngine.AndroidJNIModule.dll
UnityEngine.AnimationModule.dll
UnityEngine.AssetBundleModule.dll
UnityEngine.AudioModule.dll
UnityEngine.ClothModule.dll
UnityEngine.ClusterInputModule.dll
UnityEngine.ClusterRendererModule.dll
UnityEngine.ContentLoadModule.dll
UnityEngine.CoreModule.dll
UnityEngine.CrashReportingModule.dll
UnityEngine.DSPGraphModule.dll
UnityEngine.DirectorModule.dll
UnityEngine.GIModule.dll
UnityEngine.GameCenterModule.dll
UnityEngine.GraphicsStateCollectionSerializerModule.dll
UnityEngine.GridModule.dll
UnityEngine.HierarchyCoreModule.dll
UnityEngine.HierarchyModule.dll
UnityEngine.HotReloadModule.dll
UnityEngine.IMGUIModule.dll
UnityEngine.IdentifiersModule.dll
UnityEngine.ImageConversionModule.dll
UnityEngine.InputForUIModule.dll
UnityEngine.InputLegacyModule.dll
UnityEngine.InputModule.dll
UnityEngine.JSONSerializeModule.dll
UnityEngine.LocalizationModule.dll
UnityEngine.MarshallingModule.dll
UnityEngine.MultiplayerModule.dll
UnityEngine.ParticleSystemModule.dll
UnityEngine.PerformanceReportingModule.dll
UnityEngine.Physics2DModule.dll
UnityEngine.PhysicsBackendPhysXModule.dll
UnityEngine.PhysicsModule.dll
UnityEngine.PropertiesModule.dll
UnityEngine.RenderAs2DModule.dll
UnityEngine.RuntimeInitializeOnLoadManagerInitializerModule.dll
UnityEngine.ScreenCaptureModule.dll
UnityEngine.ShaderRuntimeModule.dll
UnityEngine.ShaderVariantAnalyticsModule.dll
UnityEngine.SharedInternalsModule.dll
UnityEngine.SpriteMaskModule.dll
UnityEngine.SpriteShapeModule.dll
UnityEngine.StreamingModule.dll
UnityEngine.SubstanceModule.dll
UnityEngine.SubsystemsModule.dll
UnityEngine.TLSModule.dll
UnityEngine.TerrainModule.dll
UnityEngine.TerrainPhysicsModule.dll
UnityEngine.TextCoreFontEngineModule.dll
UnityEngine.TextCoreTextEngineModule.dll
UnityEngine.TextRenderingModule.dll
UnityEngine.TilemapModule.dll
UnityEngine.UI.dll
UnityEngine.UIElementsModule.dll
UnityEngine.UIModule.dll
UnityEngine.UmbraModule.dll
UnityEngine.UnityAnalyticsCommonModule.dll
UnityEngine.UnityAnalyticsModule.dll
UnityEngine.UnityConnectModule.dll
UnityEngine.UnityConsentModule.dll
UnityEngine.UnityCurlModule.dll
UnityEngine.UnityWebRequestAssetBundleModule.dll
UnityEngine.UnityWebRequestAudioModule.dll
UnityEngine.UnityWebRequestModule.dll
UnityEngine.UnityWebRequestTextureModule.dll
UnityEngine.UnityWebRequestWWWModule.dll
UnityEngine.VFXModule.dll
UnityEngine.VRModule.dll
UnityEngine.VectorGraphicsModule.dll
UnityEngine.VehiclesModule.dll
UnityEngine.VideoModule.dll
UnityEngine.VirtualTexturingModule.dll
UnityEngine.WindModule.dll
UnityEngine.XRModule.dll
UnityEngine.dll
__Generated.dll
assembly-hash.txt
com.playeveryware.eos.core.dll
```
