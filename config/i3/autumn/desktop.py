#!/usr/bin/env python3
"""Local i3 controls. No network access, plug-in loading, or secret discovery."""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time

CONFIG = Path.home() / ".config"
THEME = CONFIG / "rofi/autumn.rasi"
AUDIO = CONFIG / "i3/autumn/audio.py"
BAR_CONFIG = CONFIG / "polybar/autumn.ini"
WALLPAPER = CONFIG / "i3/autumn/wallpaper.png"
PICOM_CONFIG = CONFIG / "i3/autumn/picom.conf"
LOCAL_PICOM = Path.home() / ".local/bin/picom-autumn"
MOTION_DISABLED = Path.home() / ".local/state/i3-autumn/motion-disabled"
KEYBOARD_GROUP = Path.home() / ".local/state/i3-autumn/keyboard-group"
KEYBOARD_PREVIOUS = Path.home() / ".local/state/i3-autumn/keyboard-previous"
SCRATCH_CLASS = "AutumnScratchpad"
TERMINAL_PROFILE = "Autumn"


class DesktopError(RuntimeError):
    pass


def configure_keyboard():
    # Debian 12 has no grp:ctrl_space_toggle option. i3 owns Ctrl+Space and
    # calls XkbLockGroup directly, so application/IME grabs cannot consume it.
    result = run(["setxkbmap", "-layout", "us,ru,ua", "-option", ""])
    if result.returncode:
        raise DesktopError("Не вдалося налаштувати розкладки i3.")
    # setxkbmap resets to the first group; bring back the last chosen one.
    group = saved_layout()
    if group:
        lock_layout(lambda current: group)


def saved_layout(path=None):
    try:
        group = int((path or KEYBOARD_GROUP).read_text().strip())
    except (OSError, ValueError):
        return 0
    return group if 0 <= group < 3 else 0


def save_layout(group, path=None):
    path = path or KEYBOARD_GROUP
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{group}\n")
    except OSError:
        pass  # Remembering the layout is a convenience, never fatal.


def lock_layout(choose_group):
    try:
        xlib = ctypes.CDLL("libX11.so.6")
    except OSError as error:
        raise DesktopError("Бібліотека X11 недоступна для перемикання мови.") from error
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
    xlib.XkbGetState.restype = ctypes.c_int
    xlib.XkbLockGroup.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
    xlib.XkbLockGroup.restype = ctypes.c_int
    xlib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = xlib.XOpenDisplay(None)
    if not display:
        raise DesktopError("X11 недоступний для перемикання мови.")
    try:
        state = ctypes.create_string_buffer(64)
        if xlib.XkbGetState(display, 0x0100, state) != 0:
            raise DesktopError("Не вдалося прочитати поточну розкладку.")
        group = choose_group(state.raw[0]) % 3
        if not xlib.XkbLockGroup(display, 0x0100, group):
            raise DesktopError("Не вдалося перемкнути розкладку.")
        xlib.XSync(display, False)
    finally:
        xlib.XCloseDisplay(display)
    return group


def switch_layout(pick):
    # A session input daemon can replace the map with a single layout. Recover
    # the three groups on demand without changing GNOME's saved preferences.
    mapping = run(["setxkbmap", "-query"])
    layouts = re.search(r"^layout:\s*(\S+)", mapping.stdout, re.M)
    if mapping.returncode or layouts is None or layouts[1] != "us,ru,ua":
        configure_keyboard()

    def choose(current):
        target = pick(current) % 3
        if target != current:
            save_layout(current, KEYBOARD_PREVIOUS)
        return target

    save_layout(lock_layout(choose))


def next_layout():
    switch_layout(lambda current: current + 1)


def previous_layout():
    # Like macOS Ctrl+Space: jump back to the layout used before this one.
    # With no usable history, fall back to the next layout.
    def pick(current):
        previous = saved_layout(KEYBOARD_PREVIOUS)
        return previous if previous != current else current + 1
    switch_layout(pick)


def run(argv, *, timeout=5, **kwargs):
    try:
        return subprocess.run(argv, text=True, capture_output=True,
                              timeout=timeout, check=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DesktopError(f"Не вдалося виконати {argv[0]}: {error}") from error


class Connection:
    def __init__(self, socket):
        self.socket = socket

    @classmethod
    def current(cls):
        # Resolve the socket from this X display, not an inherited I3SOCK.
        socket = run(["i3", "--get-socketpath"]).stdout.strip()
        if not socket.startswith("/"):
            raise DesktopError("Ці команди доступні лише в сесії i3.")
        connection = cls(socket)
        if not connection.alive():
            raise DesktopError("Ці команди доступні лише в сесії i3.")
        return connection

    def request(self, kind, command=None):
        argv = ["i3-msg", "-s", self.socket, "-t", kind]
        if command is not None:
            argv.append(command)
        result = run(argv, timeout=2)
        if result.returncode:
            raise DesktopError("Сесія i3 недоступна.")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DesktopError("i3 повернув некоректну відповідь.") from error

    def alive(self):
        try:
            version = self.request("get_version")
            return isinstance(version, dict) and isinstance(version.get("major"), int)
        except DesktopError:
            return False

    def command(self, command):
        replies = self.request("command", command)
        if not isinstance(replies, list) or not all(r.get("success") for r in replies):
            raise DesktopError("i3 не зміг виконати команду.")


def choose(title, rows, message=None):
    argv = ["rofi", "-dmenu", "-i", "-no-custom", "-format", "i",
            "-selected-row", "0", "-p", title, "-config", str(THEME)]
    if message:
        argv.extend(["-mesg", message])
    result = run(argv, timeout=None, input="\n".join(rows))
    if result.returncode:
        return None
    try:
        index = int(result.stdout.strip())
    except ValueError:
        return None
    return index if 0 <= index < len(rows) else None


def confirm(action, detail):
    return choose(action, ["Скасувати", action], detail) == 1


def detached(argv):
    try:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as error:
        raise DesktopError(f"Не вдалося запустити {argv[0]}: {error}") from error


def notify(message):
    if shutil.which("notify-send"):
        try:
            run(["notify-send", "--urgency=normal", "Autumn", message], timeout=2)
        except DesktopError:
            pass


def picom_program():
    for program in (shutil.which(str(LOCAL_PICOM)), shutil.which("picom")):
        if not program:
            continue
        try:
            result = run([program, "--version"])
        except DesktopError:
            continue
        version = re.match(r"^(?:picom\s+)?v?(\d+)(?:[.\s-]|$)", result.stdout.strip(), re.I)
        if result.returncode == 0 and version and int(version[1]) >= 13:
            return program
    return None


def motion(connection):
    if not picom_program():
        raise DesktopError("Для анімацій потрібен Picom 13 або новіший.")
    runtime = runtime_dir(connection)
    try:
        state = (runtime / "motion.status").read_text().strip()
    except FileNotFoundError:
        state = "unknown"
    description = {"enabled": "працюють", "disabled": "вимкнені", "failed": "зупинилися",
                   "unavailable": "недоступні"}.get(state, "невідомий")
    selected = choose("Анімації", ["Скасувати", "Увімкнути / перезапустити", "Вимкнути"],
                      "Останній перевірений стан: " + description)
    if selected in (None, 0):
        return
    if not connection.alive():
        raise DesktopError("Сесія i3 вже недоступна; дію скасовано.")
    if selected == 2:
        MOTION_DISABLED.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        MOTION_DISABLED.touch(mode=0o600, exist_ok=True)
    else:
        MOTION_DISABLED.unlink(missing_ok=True)
    (runtime / "motion.request").touch(mode=0o600, exist_ok=True)


def terminal():
    for program in ("gnome-terminal", "kitty", "alacritty", "x-terminal-emulator",
                    "i3-sensible-terminal"):
        if shutil.which(program):
            detached([program, "--profile=" + TERMINAL_PROFILE] if program == "gnome-terminal" else [program])
            return
    raise DesktopError("Термінал не знайдено.")


def find_scratch(node):
    if node.get("window_properties", {}).get("class") == SCRATCH_CLASS:
        return node["id"]
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        match = find_scratch(child)
        if match is not None:
            return match
    return None


def runtime_dir(connection):
    root = Path(os.environ.get("XDG_RUNTIME_DIR", str(Path.home() / ".cache")))
    suffix = hashlib.sha256(connection.socket.encode()).hexdigest()[:16]
    path = root / f"i3-autumn-{suffix}"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise DesktopError("Каталог стану i3 має небезпечні права доступу.")
    return path


def open_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(fd)
        raise DesktopError("Некоректний файл блокування i3.")
    return os.fdopen(fd, "r+")


def scratchpad(connection):
    runtime = runtime_dir(connection)
    with open_lock(runtime / "scratch.lock") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        match = find_scratch(connection.request("get_tree"))
        if match is not None:
            (runtime / "scratch.pending").unlink(missing_ok=True)
            connection.command(f"[con_id={match}] scratchpad show")
            return
        if not shutil.which("gnome-terminal"):
            raise DesktopError("Для висувного термінала потрібен gnome-terminal.")
        pending = runtime / "scratch.pending"
        try:
            recent_launch = time.monotonic() - float(pending.read_text()) < 30
        except (FileNotFoundError, ValueError):
            recent_launch = False
        if not recent_launch:
            detached(["gnome-terminal", "--profile=" + TERMINAL_PROFILE,
                      "--class=" + SCRATCH_CLASS, "--title=" + SCRATCH_CLASS])
            pending.write_text(str(time.monotonic()))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            match = find_scratch(connection.request("get_tree"))
            if match is not None:
                pending.unlink(missing_ok=True)
                connection.command(f"[con_id={match}] floating enable, move scratchpad, scratchpad show")
                return
            time.sleep(0.1)
        raise DesktopError("Термінал ще запускається. Натисніть F12 ще раз.")


def lock_screen():
    if not shutil.which("i3lock"):
        raise DesktopError("i3lock не встановлено.")
    result = run(["i3lock", "--color", "1c1917"], timeout=15)
    if result.returncode:
        raise DesktopError("Не вдалося заблокувати екран; наступну дію скасовано.")


def power(connection):
    rows = ["Скасувати", "Заблокувати", "Сон", "Вийти з i3",
            "Перейти до GNOME", "Перезавантажити", "Вимкнути"]
    selected = choose("Сесія", rows)
    if selected in (None, 0):
        return
    if selected == 1:
        lock_screen()
        return
    detail = "Збережіть відкриті документи перед продовженням."
    if selected == 4:
        detail = ("Збережіть документи. Після виходу виберіть користувача, "
                  "відкрийте меню сесій GDM і виберіть GNOME.")
    if not confirm(rows[selected], detail):
        return
    # Recheck after the user spent time in the confirmation dialog.
    if not connection.alive():
        raise DesktopError("Сесія i3 вже недоступна; дію скасовано.")
    if selected in (3, 4):
        connection.command("exit")
    else:
        if selected == 2:
            lock_screen()
        result = run(["systemctl", {2: "suspend", 5: "reboot", 6: "poweroff"}[selected]], timeout=30)
        if result.returncode:
            raise DesktopError("Система відхилила дію живлення.")


HELP = [
    "Win + Enter          Термінал", "Win + D              Програми",
    "Win + Tab            Вікна", "Win + C              Центр керування",
    "Win + P              Звук", "Win + Ctrl + P       Вихід звуку",
    "Win + Ctrl + Shift + P   Вхід звуку", "Ctrl + Space         Попередня мова",
    "Ctrl + Alt + Space   EN → RU → UA",
    "Win + F1             Ця довідка", "Win + F12            Висувний термінал",
    "Win + Ctrl + L       Блокування", "Win + Shift + E      Меню сесії",
    "Win + H / V          Поділ горизонтально / вертикально",
    "Win + S / W / E      Стос / вкладки / чергування поділу",
    "Win + F              Повний екран", "Win + R              Режим зміни розміру",
    "Win + Shift + T      Плаваюче вікно", "Win + T              Фокус плиток / плаваючих",
    "Win + стрілки        Перемістити фокус", "Win + Shift + стрілки   Перемістити вікно",
    "Win + 1…8            Робочі простори", "Win + Shift + 1…8    Надіслати вікно й перейти",
    "Win + Ctrl + 1…8     Надіслати вікно без переходу",
]


def menu(connection):
    rows = ["Програми", "Вікна", "Термінал", "Висувний термінал", "Звук",
            "Вихід звуку", "Вхід звуку", "Вкладки", "Стос", "Чергуйте поділ",
            "Плаваюче вікно", "Повний екран", "Клавіші", "Сесія та живлення", "Анімації"]
    selected = choose("Autumn", rows)
    if selected in (0, 1):
        detached(["rofi", "-show", ("drun", "window")[selected], "-config", str(THEME)])
    elif selected == 2:
        terminal()
    elif selected == 3:
        scratchpad(connection)
    elif selected in (4, 5, 6):
        detached([sys.executable, str(AUDIO), {4: "menu", 5: "outputs", 6: "inputs"}[selected]])
    elif selected in (7, 8, 9, 10, 11):
        connection.command({7: "layout tabbed", 8: "layout stacking", 9: "layout toggle split",
                            10: "floating toggle", 11: "fullscreen toggle"}[selected])
    elif selected == 12:
        choose("Клавіші", HELP)
    elif selected == 13:
        power(connection)
    elif selected == 14:
        motion(connection)


def stop_owned(process):
    """Only a retained Popen child can be stopped; no global process searches."""
    if process.poll() is not None:
        return
    try:
        # Every managed child was created with start_new_session=True.
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


class Supervisor:
    def __init__(self, connection, runtime):
        self.connection = connection
        self.runtime = runtime
        self.children = []
        self.bars = []
        self.compositor = None
        self.stopping = False

    def spawn(self, argv):
        child = detached(argv)
        self.children.append(child)
        return child

    def apply_motion(self, announce=False):
        if self.compositor is not None:
            stop_owned(self.compositor)
            self.children.remove(self.compositor)
            self.compositor = None
        state = "disabled" if MOTION_DISABLED.exists() else "unavailable"
        program = None if state == "disabled" else picom_program()
        if program:
            try:
                self.compositor = self.spawn([program, "--config", str(PICOM_CONFIG)])
                time.sleep(0.25)
                state = "enabled" if self.compositor.poll() is None else "failed"
            except DesktopError:
                state = "failed"
        (self.runtime / "motion.status").write_text(state)
        if state == "failed":
            notify("Анімації не запустилися. Перевірте Picom і повторіть запуск через меню.")
        elif announce:
            notify({"enabled": "Анімації увімкнено.", "disabled": "Анімації вимкнено.",
                    "unavailable": "Для анімацій потрібен Picom 13 або новіший."}[state])

    def check_motion(self):
        if self.compositor is not None and self.compositor.poll() is not None:
            self.children.remove(self.compositor)
            self.compositor = None
            if (self.runtime / "motion.status").read_text() != "failed":
                (self.runtime / "motion.status").write_text("failed")
                notify("Анімації зупинилися. Їх можна перезапустити через меню.")

    def restart_bars(self):
        for child in self.bars:
            stop_owned(child)
            self.children.remove(child)
        self.bars.clear()
        outputs = [o for o in self.connection.request("get_outputs") if o.get("active")]
        primary = next((o["name"] for o in outputs if o.get("primary")),
                       outputs[0]["name"] if outputs else None)
        # Only these two non-secret variables are changed for child inheritance.
        old_monitor = os.environ.get("AUTUMN_MONITOR")
        old_tray = os.environ.get("AUTUMN_TRAY")
        try:
            for output in outputs:
                os.environ["AUTUMN_MONITOR"] = output["name"]
                os.environ["AUTUMN_TRAY"] = "right" if output["name"] == primary else "none"
                self.bars.append(self.spawn(["polybar", "--config=" + str(BAR_CONFIG), "autumn"]))
        finally:
            for key, value in (("AUTUMN_MONITOR", old_monitor), ("AUTUMN_TRAY", old_tray)):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def configure(self):
        configure_keyboard()
        run(["xset", "r", "rate", "300", "35"])
        run(["xset", "s", "600"])
        if shutil.which("xwallpaper") and WALLPAPER.is_file():
            run(["xwallpaper", "--zoom", str(WALLPAPER)])
        else:
            run(["xsetroot", "-solid", "#1c1917"])
        if shutil.which("xss-lock") and shutil.which("i3lock"):
            self.spawn(["xss-lock", "--transfer-sleep-lock", "--", "i3lock", "--nofork", "--color", "1c1917"])
        if shutil.which("nm-applet"):
            self.spawn(["nm-applet"])
        if shutil.which("dunst"):
            self.spawn(["dunst", "-conf", str(CONFIG / "i3/autumn/dunstrc")])
        polkit_agent = Path("/usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1")
        if polkit_agent.is_file():
            self.spawn([str(polkit_agent)])
        self.restart_bars()
        self.apply_motion()

    def subscribe(self):
        try:
            subscriber = subprocess.Popen(
                ["i3-msg", "-s", self.connection.socket, "-m", "-t", "subscribe", '["shutdown","output"]'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                start_new_session=True)
        except OSError as error:
            raise DesktopError("Не вдалося стежити за станом сесії i3.") from error
        self.children.append(subscriber)
        return subscriber

    def run(self):
        # Advisory lock serializes repeated exec_always calls. No PID files are
        # used for signaling: a stale/reused PID can never target another app.
        with open_lock(self.runtime / "supervisor.lock") as lockfile:
            try:
                fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                request_bars(self.runtime)
                return
            lockfile.truncate(0)
            lockfile.write(str(os.getpid()))
            lockfile.flush()
            previous = {}
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                previous[sig] = signal.signal(sig, self.stop)
            subscriber = None
            selector = selectors.DefaultSelector()
            try:
                self.configure()
                subscriber = self.subscribe()
                selector.register(subscriber.stdout, selectors.EVENT_READ)
                failed_checks = 0
                last_check = 0.0
                while not self.stopping:
                    for key, _ in selector.select(timeout=0.5):
                        line = key.fileobj.readline()
                        if not line:
                            selector.unregister(key.fileobj)
                            stop_owned(subscriber)
                            self.children.remove(subscriber)
                            subscriber.stdout.close()
                            subscriber = None
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict) and event.get("change") == "exit":
                            self.stopping = True
                        elif isinstance(event, dict) and event.get("change") == "unspecified":
                            request_bars(self.runtime)
                    if self.stopping:
                        break
                    if time.monotonic() - last_check >= 1:
                        last_check = time.monotonic()
                        failed_checks = 0 if self.connection.alive() else failed_checks + 1
                        if failed_checks >= 4:
                            break
                        if not failed_checks and subscriber is None:
                            subscriber = self.subscribe()
                            selector.register(subscriber.stdout, selectors.EVENT_READ)
                    request = self.runtime / "bars.request"
                    if request.exists() and not failed_checks:
                        request.unlink()
                        self.restart_bars()
                    request = self.runtime / "motion.request"
                    if request.exists() and not failed_checks:
                        request.unlink()
                        self.apply_motion(announce=True)
                    self.check_motion()
            finally:
                selector.close()
                for child in reversed(self.children):
                    stop_owned(child)
                (self.runtime / "motion.status").unlink(missing_ok=True)
                for sig, handler in previous.items():
                    signal.signal(sig, handler)

    def stop(self, _signal, _frame):
        self.stopping = True


def request_bars(runtime):
    # The private 0700 runtime directory prevents other users injecting requests.
    (runtime / "bars.request").touch(mode=0o600, exist_ok=True)


def bars(connection):
    runtime = runtime_dir(connection)
    with open_lock(runtime / "supervisor.lock") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            request_bars(runtime)
            return
    detached([sys.executable, str(Path(__file__).resolve()), "session-start"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("menu", "power", "help", "terminal", "scratchpad",
                                            "lock", "session-start", "bars", "motion",
                                            "keyboard-setup", "keyboard-next", "keyboard-prev"))
    args = parser.parse_args(argv)
    try:
        connection = Connection.current()
        actions = {"menu": lambda: menu(connection), "power": lambda: power(connection),
                   "help": lambda: choose("Клавіші", HELP), "terminal": terminal,
                   "scratchpad": lambda: scratchpad(connection), "lock": lock_screen,
                   "session-start": lambda: Supervisor(connection, runtime_dir(connection)).run(),
                   "bars": lambda: bars(connection), "motion": lambda: motion(connection),
                   "keyboard-setup": configure_keyboard, "keyboard-next": next_layout,
                   "keyboard-prev": previous_layout}
        actions[args.action]()
        return 0
    except DesktopError as error:
        print(str(error), file=sys.stderr)
        notify(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
