#!/usr/bin/env python3
"""Local PipeWire/PulseAudio controls; no shell, network, or secret access."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
import time
import unicodedata


ROFI_CONFIG = str(Path.home() / ".config/rofi/autumn.rasi")
STEP = 5


class AudioError(Exception):
    """A public, non-sensitive error suitable for a desktop notification."""


def run(argv, *, input_text=None, timeout=4):
    try:
        return subprocess.run(
            argv, input=input_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError("Не вдалося запустити керування звуком.") from exc


def pactl(*args):
    result = run(["pactl", *args])
    if result.returncode != 0:
        # Server diagnostics may contain application metadata; never expose it.
        raise AudioError("Звуковий сервер недоступний або пристрій зник.")
    return result.stdout.strip()


def notify(message):
    try:
        run(["notify-send", "Звук", message], timeout=2)
    except AudioError:
        pass


def index_of(value):
    """Only decimal indices obtained from pactl may become command arguments."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def list_items(kind):
    try:
        items = json.loads(pactl("-f", "json", "list", kind))
    except (ValueError, TypeError) as exc:
        raise AudioError("Не вдалося прочитати список звукових пристроїв.") from exc
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise AudioError("Звуковий сервер повернув невідомий формат даних.")
    return items


def is_monitor(source):
    properties = source.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    monitor_of = source.get("monitor_of_sink")
    return (
        str(source.get("name", "")).endswith(".monitor")
        or properties.get("device.class") == "monitor"
        or monitor_of not in (None, -1, 4294967295, "-1", "4294967295", "n/a", "")
    )


def devices(kind):
    return [
        device for device in list_items("sinks" if kind == "output" else "sources")
        if index_of(device.get("index")) is not None
        and isinstance(device.get("name"), str) and device["name"]
    ]


def current_device(kind):
    default = pactl("get-default-sink" if kind == "output" else "get-default-source")
    device = next((item for item in devices(kind) if item["name"] == default), None)
    if device is None:
        raise AudioError("Типовий звуковий пристрій зараз недоступний.")
    return device


def label(value):
    # Each device occupies exactly one plain-text row. No Pango markup is enabled.
    return "".join(
        " " if unicodedata.category(char).startswith("C") else char
        for char in str(value)
    )[:180]


def choose(prompt, labels):
    if not labels:
        raise AudioError("Немає доступних звукових пристроїв.")
    result = run(
        ["rofi", "-dmenu", "-i", "-no-custom", "-format", "i",
         "-no-markup-rows", "-config", ROFI_CONFIG, "-p", prompt],
        input_text="\n".join(label(item) for item in labels) + "\n", timeout=None,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise AudioError("Не вдалося відкрити меню звуку.")
    selection = index_of(result.stdout.strip())
    if selection is None or selection >= len(labels):
        raise AudioError("Меню повернуло некоректний вибір.")
    return selection


def select_device(kind):
    available = devices(kind)
    if kind == "input":
        available = [item for item in available if not is_monitor(item)]
    default = pactl("get-default-sink" if kind == "output" else "get-default-source")
    labels = [
        ("[*] " if item["name"] == default else "    ")
        + label(item.get("description") or item["name"])
        for item in available
    ]
    selection = choose("Вихід звуку" if kind == "output" else "Мікрофон", labels)
    if selection is None:
        return
    selected = available[selection]

    # The user may leave the menu open while unplugging a headset. Re-read before
    # changing anything, and use the validated current device name and index.
    fresh = devices(kind)
    target = next((item for item in fresh if item["name"] == selected["name"]), None)
    if target is None or (kind == "input" and is_monitor(target)):
        raise AudioError("Обраний пристрій більше недоступний. Відкрийте меню знову.")
    streams = list_items("sink-inputs" if kind == "output" else "source-outputs")
    source_map = {index_of(item["index"]): item for item in fresh}
    target_index = str(index_of(target["index"]))
    # set-default accepts a symbolic NAME (unlike stream movement). End global
    # option parsing so even an unexpected device name cannot become an option.
    pactl("--", "set-default-sink" if kind == "output" else "set-default-source", target["name"])
    failed = False
    for stream in streams:
        stream_index = index_of(stream.get("index"))
        if stream_index is None:
            continue
        if kind == "input":
            source = source_map.get(index_of(stream.get("source")))
            # Preserve desktop/screen recording and unknown source streams.
            if source is None or is_monitor(source):
                continue
        try:
            pactl("move-sink-input" if kind == "output" else "move-source-output",
                  str(stream_index), target_index)
        except AudioError:
            # A stream can end independently while this short snapshot is routed.
            failed = True
    if failed:
        notify("Типовий пристрій змінено; частину потоків не вдалося перемістити.")


def volume_percent(device):
    volume = device.get("volume")
    if not isinstance(volume, dict) or not volume:
        raise AudioError("Не вдалося прочитати гучність пристрою.")
    values = []
    for channel in volume.values():
        if not isinstance(channel, dict):
            continue
        raw = channel.get("value")
        try:
            percent = float(raw) * 100 / 65536 if raw is not None else float(
                str(channel.get("value_percent", "")).removesuffix("%")
            )
        except (ValueError, TypeError, OverflowError):
            continue
        if math.isfinite(percent) and percent >= 0:
            values.append(percent)
    if not values:
        raise AudioError("Не вдалося прочитати гучність пристрою.")
    return round(max(values))


def change_volume(delta):
    device = current_device("output")
    value = max(0, min(100, volume_percent(device) + delta))
    pactl("set-sink-volume", str(index_of(device["index"])), f"{value}%")


def toggle_mute(kind):
    device = current_device(kind)
    if kind == "input" and is_monitor(device):
        raise AudioError("Оберіть мікрофон у меню звуку перед зміною його стану.")
    pactl("set-sink-mute" if kind == "output" else "set-source-mute",
          str(index_of(device["index"])), "toggle")


def status(kind):
    try:
        device = current_device(kind)
        if kind == "input":
            if is_monitor(device):
                return "MIC —"
            return "MIC OFF" if device.get("mute") else "MIC ON"
        if device.get("mute"):
            return "VOL MUTE"
        # Only fixed text and an integer: never interpolate device metadata into
        # Polybar's %{...} formatting language. A lone percent is ordinary text.
        return f"VOL {volume_percent(device)}%"
    except AudioError:
        return "VOL —" if kind == "output" else "MIC —"


def follow_events(kind, stream, refresh):
    """Coalesce queued server events, excluding our own pactl client events."""
    facility = b"sink" if kind == "output" else b"source"
    relevant = re.compile(rb"\bon (?:" + facility + rb"|server|card) #\d+")
    pending = b""
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        while selector.select():
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                return
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()[-4096:]
            if any(relevant.search(line) for line in lines):
                refresh()


def watch(kind):
    """Push changed labels immediately; reconnect when the audio server returns."""
    previous = None

    def refresh():
        nonlocal previous
        value = status(kind)
        if value != previous:
            print(value, flush=True)
            previous = value

    # Force stable event names. Only these ordinary connection settings are
    # needed; no credential variables or unrelated environment are inspected.
    environment = {"LC_ALL": "C", "PATH": os.environ.get("PATH", os.defpath)}
    for name in ("HOME", "XDG_RUNTIME_DIR", "PULSE_SERVER", "PULSE_RUNTIME_PATH"):
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    try:
        while True:
            subscriber = None
            try:
                subscriber = subprocess.Popen(
                    ["pactl", "subscribe"], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=environment,
                )
                # Subscribe before the first snapshot so changes during startup
                # are queued instead of being lost between snapshot and listen.
                refresh()
                follow_events(kind, subscriber.stdout, refresh)
            except OSError:
                pass
            finally:
                if subscriber is not None:
                    subscriber.stdout.close()
                    if subscriber.poll() is None:
                        subscriber.terminate()
                        try:
                            subscriber.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            subscriber.kill()
                            subscriber.wait(timeout=2)
            refresh()
            time.sleep(1)
    except (BrokenPipeError, KeyboardInterrupt):
        return


def mixer():
    try:
        subprocess.Popen(["pavucontrol"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as exc:
        raise AudioError("Мікшер pavucontrol не встановлено або він недоступний.") from exc


def menu():
    actions = [
        ("Вихід звуку", lambda: select_device("output")),
        ("Мікрофон / вхід звуку", lambda: select_device("input")),
        ("Повний мікшер", mixer),
        ("Увімкнути / вимкнути звук", lambda: toggle_mute("output")),
        ("Увімкнути / вимкнути мікрофон", lambda: toggle_mute("input")),
    ]
    selection = choose("Звук", [item[0] for item in actions])
    if selection is not None:
        actions[selection][1]()


def main(argv=None):
    actions = {
        "menu": menu,
        "outputs": lambda: select_device("output"),
        "inputs": lambda: select_device("input"),
        "status-output": lambda: print(status("output")),
        "status-input": lambda: print(status("input")),
        "watch-output": lambda: watch("output"),
        "watch-input": lambda: watch("input"),
        "volume-up": lambda: change_volume(STEP),
        "volume-down": lambda: change_volume(-STEP),
        "mute-output": lambda: toggle_mute("output"),
        "mute-input": lambda: toggle_mute("input"),
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=actions)
    args = parser.parse_args(argv)
    try:
        actions[args.action]()
    except AudioError as exc:
        notify(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
