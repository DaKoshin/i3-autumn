#!/usr/bin/env python3
"""Install or remove the optional «Autumn» gnome-terminal profile.

The profile lives in dconf (GNOME settings), so this is a separate, explicit
step and is not part of install.sh. It only adds one profile next to the
existing ones and never changes the default profile.
"""
import argparse
import ast
import subprocess
import sys

UUID = "3f6a1c52-7d0e-4b8a-9c21-a1b2c3d4e5f6"
NAME = "Autumn"
PROFILES = "/org/gnome/terminal/legacy/profiles:/"
LIST_SCHEMA = ("org.gnome.Terminal.ProfilesList", "list")

PALETTE = (
    (33, 29, 25), (214, 125, 106), (184, 194, 139), (240, 192, 118),
    (140, 170, 185), (200, 150, 160), (150, 190, 160), (240, 234, 226),
    (145, 129, 113), (232, 145, 126), (204, 213, 158), (247, 208, 140),
    (164, 194, 208), (218, 168, 178), (172, 210, 180), (255, 252, 246),
)


def rgb(color):
    return "'rgb({},{},{})'".format(*color)


def profile_text():
    palette = ", ".join(rgb(color) for color in PALETTE)
    return "\n".join((
        f"[:{UUID}]",
        f"visible-name='{NAME}'",
        f"background-color={rgb((33, 29, 25))}",
        f"foreground-color={rgb((250, 246, 239))}",
        "use-theme-colors=false",
        "bold-is-bright=false",
        "cursor-colors-set=true",
        f"cursor-background-color={rgb((231, 181, 109))}",
        f"cursor-foreground-color={rgb((33, 29, 25))}",
        "highlight-colors-set=true",
        f"highlight-background-color={rgb((81, 64, 48))}",
        f"highlight-foreground-color={rgb((250, 246, 240))}",
        "cursor-shape='underline'",
        "default-size-columns=120",
        f"palette=[{palette}]",
        "",
    ))


def run(argv, **kwargs):
    try:
        return subprocess.run(argv, text=True, capture_output=True, timeout=10, check=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"Не вдалося виконати {argv[0]}: {error}")


def read_list():
    result = run(["gsettings", "get", *LIST_SCHEMA])
    if result.returncode:
        raise SystemExit("gnome-terminal недоступний: gsettings не повернув список профілів.")
    try:
        return list(ast.literal_eval(result.stdout.strip().removeprefix("@as ")))
    except (ValueError, SyntaxError):
        raise SystemExit("Не вдалося розібрати список профілів gnome-terminal.")


def write_list(profiles):
    value = "[" + ", ".join(repr(item) for item in profiles) + "]"
    if run(["gsettings", "set", *LIST_SCHEMA, value]).returncode:
        raise SystemExit("Не вдалося оновити список профілів gnome-terminal.")


def install():
    profiles = read_list()
    if run(["dconf", "load", PROFILES], input=profile_text()).returncode:
        raise SystemExit("Не вдалося записати профіль у dconf.")
    if UUID not in profiles:
        write_list(profiles + [UUID])
    print(f"Профіль «{NAME}» встановлено. Типовий профіль не змінено.")


def remove():
    profiles = read_list()
    if UUID in profiles:
        write_list([item for item in profiles if item != UUID])
    run(["dconf", "reset", "-f", f"{PROFILES}:{UUID}/"])
    print(f"Профіль «{NAME}» видалено.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("install", "remove"), default="install")
    {"install": install, "remove": remove}[parser.parse_args(argv).action]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
