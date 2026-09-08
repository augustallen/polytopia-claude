#!/usr/bin/env python3
"""Screen-record the Polytopia window while a harness script plays, then stop the recording cleanly.

    record_match.py -- scripts/play_deathmatch.py --p1 claude:claude-fable-5-1:medium --p2 codex:gpt-6-astra:medium
    record_match.py --fps 10 --width 1920 --out recordings/game4.mp4 -- scripts/play_domination.py

Polytopia has no replay for offline games (replays are fetched from Midjiwan's servers for online matches
only), so the recording is the shareable record. ffmpeg captures the screen region under the game window's
client area with gdigrab (the window must be on screen and not minimized; gdigrab's window-title mode freezes
on the first frame because the Unity DirectX surface never repaints through GDI), scaled to --width, at --fps,
H.264. The file is written as a fragmented MP4 so an abrupt stop still leaves a playable file; on a normal
stop ffmpeg is asked to finish ('q') and the video is remuxed to a plain MP4. Exit code is the played
script's exit code.
"""
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def window_region(title: str) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the window's client area in physical screen pixels (DPI aware)."""
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        raise SystemExit(f"no window titled {title!r} (is the game running?)")
    if user32.IsIconic(hwnd):
        raise SystemExit(f"window {title!r} is minimized; restore it so the screen region can be captured")
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    return origin.x, origin.y, w - (w % 2), h - (h % 2)


def find_ffmpeg(explicit: str | None) -> str:
    if explicit:
        return explicit
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for exe in (home / "tools" / "ffmpeg").rglob("ffmpeg.exe"):
        return str(exe)
    raise SystemExit("ffmpeg not found: install it or pass --ffmpeg")


def start_recording(ffmpeg: str, out: Path, *, title: str, fps: int, width: int, crf: int) -> subprocess.Popen:
    out.parent.mkdir(parents=True, exist_ok=True)
    x, y, w, h = window_region(title)
    print(f"capturing screen region {w}x{h} at ({x},{y}) under window {title!r}", flush=True)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
           "-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "0",
           "-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{w}x{h}", "-i", "desktop",
           "-vf", f"scale={width}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-g", str(fps * 5),
           "-movflags", "+frag_keyframe+empty_moov+default_base_moof", str(out)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def stop_recording(proc: subprocess.Popen, timeout: float = 30) -> str:
    try:
        if proc.poll() is None and proc.stdin:
            proc.stdin.write("q\n")
            proc.stdin.flush()
    except OSError:
        pass
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    return (err or "")[-800:]


def remux(ffmpeg: str, src: Path) -> Path:
    """Fragmented MP4 -> plain MP4 with a proper index (seekable in every player)."""
    final = src.with_name(src.stem + ".final.mp4")
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-c", "copy",
                        "-movflags", "+faststart", str(final)], capture_output=True, text=True)
    if r.returncode == 0 and final.exists() and final.stat().st_size > 0:
        src.unlink()
        final.rename(src)
    return src


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ffmpeg", default=None)
    ap.add_argument("--title", default="Polytopia", help="window title to capture")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--crf", type=int, default=24)
    ap.add_argument("--out", default=None, help="output .mp4 (default recordings/<stamp>-<script>.mp4)")
    ap.add_argument("--lead", type=float, default=2.0, help="seconds of recording before the script starts")
    ap.add_argument("--tail", type=float, default=8.0, help="seconds of recording after the script exits")
    ap.add_argument("script", nargs=argparse.REMAINDER, help="-- then the harness script and its arguments")
    args = ap.parse_args()
    script = [a for a in args.script if a != "--"]
    if not script:
        ap.error("give the script to run after --")
    ffmpeg = find_ffmpeg(args.ffmpeg)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path("recordings") / f"{stamp}-{Path(script[0]).stem}.mp4"

    rec = start_recording(ffmpeg, out, title=args.title, fps=args.fps, width=args.width, crf=args.crf)
    time.sleep(args.lead)
    if rec.poll() is not None:
        print("recording failed to start:", stop_recording(rec), file=sys.stderr)
        return 4
    print(f"recording {out} ({args.fps} fps, {args.width}px wide) while running: {' '.join(script)}", flush=True)
    t0 = time.monotonic()
    try:
        code = subprocess.call([sys.executable, *script], cwd=str(HERE.parent))
    finally:
        time.sleep(args.tail)
        err = stop_recording(rec)
        remux(ffmpeg, out)
        size = out.stat().st_size if out.exists() else 0
        print(f"recording stopped after {(time.monotonic() - t0) / 60:.1f} min: {out} ({size / 1e6:.0f} MB)"
              + (f"; ffmpeg said: {err.strip()}" if err.strip() else ""), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
