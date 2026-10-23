#!/usr/bin/env python3
"""Install only the Autumn desktop allowlist, with backups and guarded rollback."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "i3/config", "i3/autumn/desktop.py", "i3/autumn/audio.py",
    "i3/autumn/wallpaper.png", "i3/autumn/dunstrc", "polybar/autumn.ini", "rofi/autumn.rasi",
    "i3/autumn/picom.conf",
)
REQUIRED = ("i3", "i3-msg", "polybar", "rofi", "python3", "pactl",
            "pavucontrol", "setxkbmap", "xset", "xss-lock", "i3lock", "xwallpaper")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(home, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Path outside target home")
    result = home / relative
    part = home
    for name in relative.parts:
        part = part / name
        if part.is_symlink():
            raise ValueError(f"Refusing to replace a symlink: {part}")
    if result.exists() and not result.is_file():
        raise ValueError(f"Expected a regular file: {result}")
    return result


def atomic_copy(source, destination, mode):
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".autumn-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(home, check=False):
    pending = []
    for name in FILES:
        source = safe_path(ROOT, "config/" + name)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing or unsafe source: {source}")
        relative = ".config/" + name
        target = safe_path(home, relative)
        pending.append((source, target, relative))
    if check:
        return {"files": [str(target) for _, target, _ in pending],
                "missing_commands": [name for name in REQUIRED if not shutil.which(name)]}
    missing = [name for name in REQUIRED if not shutil.which(name)]
    if missing:
        raise ValueError("Missing dependencies: " + ", ".join(missing))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    # Check all parent paths before creating any backup directory.
    backup = safe_path(home, f".local/state/i3-autumn/backups/{stamp}/manifest.json").parent
    backup.mkdir(parents=True, mode=0o700)
    entries = []
    for source, target, relative in pending:
        entry = {"path": relative, "existed": target.exists(),
                 "installed_sha256": digest(source)}
        if target.exists():
            entry["original_mode"] = target.stat().st_mode & 0o777
            entry["original_sha256"] = digest(target)
            saved = backup / "original" / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        entries.append(entry)
    manifest = {"home": str(home), "entries": entries}
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    applied = []
    try:
        for (source, target, _), entry in zip(pending, entries):
            atomic_copy(source, target, 0o755 if source.suffix == ".py" else 0o644)
            applied.append((target, entry))
    except Exception:
        for target, entry in reversed(applied):
            if entry["existed"]:
                atomic_copy(backup / "original" / entry["path"], target, entry["original_mode"])
            else:
                target.unlink(missing_ok=True)
        raise
    return {"installed": len(entries), "backup": str(backup),
            "session_restarted": False}


def restore(home, backup):
    backup = backup.expanduser().absolute()
    allowed_root = home / ".local/state/i3-autumn/backups"
    if backup.parent != allowed_root:
        raise ValueError("Backup must be a direct child of this user's Autumn backup directory")
    manifest_path = safe_path(home, (backup / "manifest.json").relative_to(home))
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("home") != str(home):
        raise ValueError("Backup belongs to a different target home")
    entries = manifest.get("entries", [])
    expected = {".config/" + name for name in FILES}
    legacy = expected - {".config/i3/autumn/picom.conf"}
    actual = {e.get("path") for e in entries}
    if actual not in (expected, legacy) or len(entries) != len(actual):
        raise ValueError("Invalid backup allowlist")
    # Preflight every file: never discard changes made since installation.
    for entry in entries:
        target = safe_path(home, entry["path"])
        if not target.exists() or digest(target) != entry["installed_sha256"]:
            raise ValueError(f"File changed since installation; preserve/reconcile it first: {target}")
        if entry["existed"]:
            original = safe_path(backup, "original/" + entry["path"])
            if not original.is_file() or digest(original) != entry.get("original_sha256"):
                raise ValueError("Original backup file is missing or changed")
    with tempfile.TemporaryDirectory(prefix="restore-", dir=backup) as temporary:
        staging = Path(temporary)
        for entry in entries:
            saved = staging / entry["path"]
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(home / entry["path"], saved)
        applied = []
        try:
            for entry in reversed(entries):
                target = home / entry["path"]
                if entry["existed"]:
                    atomic_copy(backup / "original" / entry["path"], target, entry["original_mode"])
                else:
                    target.unlink()
                applied.append(entry)
        except Exception:
            for entry in reversed(applied):
                saved = staging / entry["path"]
                atomic_copy(saved, home / entry["path"], saved.stat().st_mode & 0o777)
            raise
    return {"restored": len(entries), "session_restarted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--target-home", type=Path, default=Path.home())
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    home = args.target_home.expanduser().resolve()
    try:
        result = restore(home, args.restore) if args.restore else install(home, args.check)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as error:
        print(f"Autumn: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
