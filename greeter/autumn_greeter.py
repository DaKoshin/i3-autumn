#!/usr/bin/env python3
"""Autumn login screen for LightDM. No network access, telemetry, or secret discovery.

LightDM owns PAM, the X server and the session; this program only draws the
login card and passes the typed answers to LightDM. `--demo` uses a fake
backend (password: autumn) so the screen can be previewed without LightDM.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

WALLPAPER = Path("/usr/share/autumn-greeter/wallpaper.png")
PREFERRED_SESSIONS = ("i3", "i3-with-shmlog")
DEMO_PASSWORD = "autumn"

CSS = b"""
window { background-color: #211d19; background-size: cover; background-position: center; }
.card { background-color: #211d19; border: 2px solid #514030; border-radius: 12px; padding: 28px; }
.title { color: #e7b56d; font-family: "Fira Code"; font-weight: 500; font-size: 20px; letter-spacing: 4px; }
.clock { color: #e5d5c3; font-family: "Fira Code"; font-size: 40px; }
.date, .hint { color: #a89785; font-size: 13px; }
.error { color: #bf6e5d; font-size: 13px; background: transparent; }
label { color: #e5d5c3; }
entry, combobox button { background: #2c251f; color: #e5d5c3; border: 1px solid #514030;
    border-radius: 8px; padding: 8px 10px; box-shadow: none; }
entry:focus { border-color: #cc915f; }
button { background: #342a22; color: #e7b56d; border: 1px solid #514030; border-radius: 8px;
    padding: 8px 14px; box-shadow: none; background-image: none; }
button:hover { background: #514030; }
button.login { color: #211d19; background: #e7b56d; border-color: #e7b56d; }
button.login:hover { background: #cc915f; }
button.login label { color: #211d19; }
button.power label { color: #a89785; }
button.power { color: #a89785; }
"""


def pick_session(sessions, remembered=None):
    """Return the session key to start: remembered, else i3, else the first one."""
    keys = [key for key, _name in sessions]
    for candidate in (remembered, *PREFERRED_SESSIONS):
        if candidate in keys:
            return candidate
    return keys[0] if keys else None


def visible_users(users, minimum_uid=1000):
    return [user for user in users if user[2] >= minimum_uid]


class DemoBackend:
    """Stand-in for LightDM so the layout can be checked in a nested X server."""
    can_power = True

    def __init__(self):
        self.users = [("demo", "Осінній користувач", 1000), ("guest", "Гість", 1001)]
        self.sessions = [("i3", "i3 · Autumn"), ("gnome", "GNOME")]
        self.log = []
        self._user = None

    def hostname(self):
        return "autumn-demo"

    def start(self, on_prompt, on_message, on_done):
        self._cb = (on_prompt, on_message, on_done)

    def authenticate(self, user):
        self._user = user
        self._cb[0]("Пароль")

    def respond(self, secret):
        self._cb[2](secret == DEMO_PASSWORD)

    def cancel(self):
        self._user = None

    def start_session(self, session):
        self.log.append(("session", self._user, session))
        return True

    def power(self, action):
        self.log.append(("power", action))


class LightDMBackend:
    def __init__(self):
        import gi
        gi.require_version("LightDM", "1")
        from gi.repository import LightDM
        self.lightdm = LightDM
        self.greeter = LightDM.Greeter()
        self.greeter.connect_to_daemon_sync()
        self.can_power = True

    @property
    def users(self):
        return [(u.get_name(), u.get_display_name(), u.get_uid())
                for u in self.lightdm.UserList.get_instance().get_users()]

    @property
    def sessions(self):
        return [(s.get_key(), s.get_name()) for s in self.lightdm.get_sessions()]

    def hostname(self):
        return self.lightdm.get_hostname()

    def start(self, on_prompt, on_message, on_done):
        self.greeter.connect("show-prompt", lambda _g, text, _kind: on_prompt(text))
        self.greeter.connect("show-message", lambda _g, text, _kind: on_message(text))
        self.greeter.connect("authentication-complete",
                             lambda g: on_done(g.get_is_authenticated()))

    def authenticate(self, user):
        self.greeter.authenticate(user)

    def respond(self, secret):
        self.greeter.respond(secret)

    def cancel(self):
        self.greeter.cancel_authentication()

    def start_session(self, session):
        return self.greeter.start_session_sync(session)

    def power(self, action):
        getattr(self.lightdm, action)()


def build_ui(backend, remembered_user=None, remembered_session=None):
    import time
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    provider = Gtk.CssProvider()
    css = CSS
    if WALLPAPER.is_file() or DEMO_WALLPAPER.is_file():
        image = WALLPAPER if WALLPAPER.is_file() else DEMO_WALLPAPER
        css += b'window { background-image: url("%s"); }' % str(image).encode()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    window = Gtk.Window(decorated=False)
    # LightDM runs no window manager, so fullscreen() would be ignored.
    screen = Gdk.Screen.get_default()
    window.set_default_size(screen.get_width(), screen.get_height())
    window.move(0, 0)
    window.connect("destroy", Gtk.main_quit)
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    window.add(outer)
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    card.get_style_context().add_class("card")
    card.set_size_request(380, -1)
    card.set_halign(Gtk.Align.CENTER)
    card.set_valign(Gtk.Align.CENTER)
    outer.pack_start(card, True, False, 0)

    def label(text, css_class, xalign=0.5):
        item = Gtk.Label(label=text, xalign=xalign)
        item.get_style_context().add_class(css_class)
        return item

    clock = label("", "clock")
    date = label("", "date")
    card.pack_start(label("AUTUMN", "title"), False, False, 0)
    card.pack_start(clock, False, False, 0)
    card.pack_start(date, False, False, 0)

    users = visible_users(backend.users)
    user_box = Gtk.ComboBoxText()
    for name, display, _uid in users:
        user_box.append(name, display or name)
    user_box.set_active_id(remembered_user if any(u[0] == remembered_user for u in users) else None)
    if user_box.get_active_id() is None and users:
        user_box.set_active(0)
    secret = Gtk.Entry(visibility=False, placeholder_text="Пароль", activates_default=True)
    session_box = Gtk.ComboBoxText()
    for key, name in backend.sessions:
        session_box.append(key, name)
    session_box.set_active_id(pick_session(backend.sessions, remembered_session))
    message = label("", "error")
    message.set_line_wrap(True)
    login = Gtk.Button(label="Увійти")
    login.get_style_context().add_class("login")

    for caption, widget in (("Користувач", user_box), ("Пароль", secret), ("Сесія", session_box)):
        card.pack_start(label(caption, "hint", 0), False, False, 0)
        card.pack_start(widget, False, False, 0)
    card.pack_start(message, False, False, 0)
    card.pack_start(login, False, False, 0)

    power_row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
    for caption, action in (("Перезавантажити", "restart"), ("Вимкнути", "shutdown")):
        button = Gtk.Button(label=caption)
        button.get_style_context().add_class("power")
        button.connect("clicked", lambda _b, a=action: confirm_power(a))
        power_row.pack_start(button, False, False, 0)
    if backend.can_power:
        card.pack_start(power_row, False, False, 0)
    card.pack_start(label(backend.hostname(), "hint"), False, False, 0)

    def confirm_power(action):
        names = {"restart": "перезавантажити", "shutdown": "вимкнути"}
        dialog = Gtk.MessageDialog(transient_for=window, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO,
                                   text=f"Справді {names[action]} комп'ютер?")
        if dialog.run() == Gtk.ResponseType.YES:
            backend.power(action)
        dialog.destroy()

    state = {"prompted": False}

    def on_prompt(_text):
        state["prompted"] = True
        backend.respond(secret.get_text())

    def show_message(text):
        message.set_text(text)
        message.set_visible(bool(text))

    def on_message(text):
        show_message(text)

    def on_done(ok):
        secret.set_text("")
        state["prompted"] = False
        if ok and backend.start_session(session_box.get_active_id()):
            Gtk.main_quit()
            return
        show_message("Невірний пароль або помилка входу.")
        secret.grab_focus()

    def attempt(_widget=None):
        user = user_box.get_active_id()
        if not user or not secret.get_text():
            return
        show_message("")
        backend.cancel()
        backend.authenticate(user)

    backend.start(on_prompt, on_message, on_done)
    login.connect("clicked", attempt)
    secret.connect("activate", attempt)

    def tick():
        now = time.localtime()
        clock.set_text(time.strftime("%H:%M", now))
        date.set_text(time.strftime("%a  %d %b", now))
        return True

    tick()
    GLib.timeout_add_seconds(5, tick)
    window.show_all()
    message.hide()
    secret.grab_focus()
    return window, {"user": user_box, "secret": secret, "session": session_box,
                    "message": message, "login": login}


DEMO_WALLPAPER = Path(__file__).resolve().parents[1] / "config/i3/autumn/wallpaper.png"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="fake backend, no LightDM")
    args = parser.parse_args(argv)
    try:
        backend = DemoBackend() if args.demo else LightDMBackend()
    except (ImportError, ValueError) as error:
        print(f"LightDM недоступний: {error}", file=sys.stderr)
        return 1
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    build_ui(backend)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
