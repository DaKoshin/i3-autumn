#!/usr/bin/env python3
"""Render a disposable nested X11 preview; never control the parent desktop."""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent
OUT = ROOT / ".preview"


def main():
    OUT.mkdir(exist_ok=True)
    display = next((f":{n}" for n in range(90, 100)
                    if not Path(f"/tmp/.X11-unix/X{n}").exists()
                    and not Path(f"/tmp/.X{n}-lock").exists()), None)
    if display is None:
        raise RuntimeError("No free nested display")
    procs = []
    handles = []

    def spawn(args, env, name, **kw):
        log = open(OUT / f"{name}.log", "w")
        handles.append(log)
        proc = subprocess.Popen(args, env=env, stdout=log, stderr=log,
                                start_new_session=True, **kw)
        procs.append(proc)
        return proc

    def run(args, env):
        return subprocess.run(args, env=env, check=True, capture_output=True,
                              text=True, timeout=10).stdout

    try:
        spawn(["Xephyr", display, "-ac", "-screen", "1600x900", "-noreset",
               "-nolisten", "tcp", "-title", "Autumn — isolated i3 preview"],
              os.environ.copy(), "xephyr")
        env = os.environ.copy()
        for name in ("I3SOCK", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
                     "WAYLAND_DISPLAY", "SESSION_MANAGER"):
            env.pop(name, None)
        env["DISPLAY"] = display
        runtime = OUT / f"runtime-{os.getpid()}"
        runtime.mkdir(mode=0o700, exist_ok=True)
        env["XDG_RUNTIME_DIR"] = str(runtime)
        env["PULSE_SERVER"] = f"unix:/run/user/{os.getuid()}/pulse/native"
        for _ in range(50):
            try:
                run(["xset", "q"], env)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                time.sleep(.1)
        else:
            raise RuntimeError("Nested display did not start")
        config = (ROOT / "config/i3/config").read_text()
        config = "\n".join(line for line in config.splitlines()
                           if not line.startswith("exec"))
        config += f'\nipc-socket "{runtime}/ipc.sock"\n'
        config = config.replace("~/.config/", str(ROOT / "config") + "/")
        (OUT / "i3.config").write_text(config)
        spawn(["i3", "-c", str(OUT / "i3.config")], env, "i3")
        env["I3SOCK"] = str(runtime / "ipc.sock")
        for _ in range(60):
            try:
                run(["i3-msg", "-t", "get_version"], env)
                break
            except subprocess.CalledProcessError:
                time.sleep(.1)
        else:
            raise RuntimeError("Nested i3 did not start")
        run(["python3", str(ROOT / "config/i3/autumn/desktop.py"), "keyboard-setup"], env)
        run(["xwallpaper", "--zoom", str(ROOT / "config/i3/autumn/wallpaper.png")], env)
        bar = (ROOT / "config/polybar/autumn.ini").read_text()
        bar = bar.replace("~/.config/", str(ROOT / "config") + "/")
        (OUT / "polybar.ini").write_text(bar)
        env["AUTUMN_MONITOR"] = "default"
        env["AUTUMN_TRAY"] = "none"
        spawn(["polybar", "-c", str(OUT / "polybar.ini"), "autumn"], env, "polybar")
        # A private bus keeps the notification test separate from GNOME.
        notifications = spawn(["dbus-run-session", "--", "dunst", "-conf",
                               str(ROOT / "config/i3/autumn/dunstrc")], env, "dunst")
        time.sleep(2)
        if notifications.poll() is not None:
            raise RuntimeError("Dunst exited during startup; inspect log")
        # XTest connects explicitly and exclusively to the newly created display.
        xlib = ctypes.CDLL("libX11.so.6")
        xtst = ctypes.CDLL("libXtst.so.6")
        xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        connection = xlib.XOpenDisplay(display.encode())
        if not connection:
            raise RuntimeError("Cannot open nested display for key verification")
        xlib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xlib.XKeysymToKeycode.restype = ctypes.c_uint
        xlib.XFlush.argtypes = [ctypes.c_void_p]
        xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xlib.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                          ctypes.c_int, ctypes.c_ulong]

        def group():
            state = ctypes.create_string_buffer(64)
            if xlib.XkbGetState(connection, 0x0100, state) != 0:
                raise RuntimeError("XKB state unavailable")
            return state.raw[0]

        groups = [group()]
        for _ in range(3):
            mod = xlib.XKeysymToKeycode(connection, 0xffe3)
            alt = xlib.XKeysymToKeycode(connection, 0xffe9)
            space = xlib.XKeysymToKeycode(connection, 0x20)
            # Ctrl+Alt+Space cycles EN -> RU -> UA (Ctrl+Space returns to the previous layout).
            for key, pressed in ((mod, 1), (alt, 1), (space, 1), (space, 0), (alt, 0), (mod, 0)):
                xtst.XTestFakeKeyEvent(connection, key, pressed, 0)
            xlib.XFlush(connection)
            time.sleep(.2)
            groups.append(group())
        xlib.XCloseDisplay(connection)
        if groups != [0, 1, 2, 0]:
            raise RuntimeError(f"Language switching failed: {groups}")
        (OUT / "keyboard-check.json").write_text(json.dumps({"groups": groups}))
        # Render the actual theme, with non-executing sample menu entries.
        menu = spawn(["rofi", "-config", str(ROOT / "config/rofi/autumn.rasi"),
                      "-dmenu", "-p", "Осінній простір", "-mesg",
                      "Ctrl+Space · попередня мова    |    Win+F1 · усі клавіші"],
                     env, "rofi", stdin=subprocess.PIPE, text=True)
        menu.stdin.write("Застосунки\nВікна та тайлінг\nВихід звуку\nМікрофон\nГарячі клавіші\nСесія i3 / GNOME\n")
        menu.stdin.close()
        time.sleep(2)
        if menu.poll() is not None:
            raise RuntimeError("Rofi exited before screenshot; inspect log")
        run(["import", "-window", "root", str(OUT / "desktop.png")], env)
        print(json.dumps({"preview": str(OUT / "desktop.png"),
                          "keyboard_groups": groups, "display": display}))
    finally:
        for proc in reversed(procs):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
