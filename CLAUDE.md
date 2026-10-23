# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules from AGENTS.md (mandatory; the file is in Ukrainian)

Read `AGENTS.md` before any task. Key points:

- **Privacy boundary:** never open, copy, modify or transmit `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube`, `~/.password-store`, keyrings, browser profiles, `.env*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `credentials*`, shell history, `/proc/*/environ`. Do not run `env`/`printenv`, bulk dconf dumps, or recursive searches of `$HOME`. Do not use the SSH agent or credential helpers. If a task truly needs a secret, stop and get explicit permission for that exact path and action.
- **No system-level changes:** do not touch SSH/GPG, PAM, sudo, polkit, firewall, GNOME config, display manager or system keyboard layout without explicit permission.
- **New widgets** must not make network requests, collect telemetry, read secrets, add unvetted third-party plugins, or use `curl | sh` / `eval` on menu data.
- **Session safety:** never log out, lock, reboot or power off during checks. Run i3/Polybar changes only inside i3 (or the nested Xephyr preview); never add them to global GNOME autostart or shell startup files.
- **Backups:** before replacing a config, make a dated backup of only the specific files being changed. Do not install packages or write outside the working folder without permission.
- AGENTS.md is guidance for agents, not an OS sandbox; don't claim otherwise.

## Commands

```sh
python3 -m unittest discover -s tests -v          # all tests
python3 -m unittest tests.test_audio -v           # one module
python3 -m unittest tests.test_audio.AudioTests.test_rofi_escape_returns_none   # one test
i3 -C -c config/i3/config                         # validate i3 config syntax
bash -n install.sh                                # validate installer syntax
./install.sh --check                              # read-only check of bundle and deps (no sudo)
python3 preview.py                                # render nested Xephyr preview -> .preview/desktop.png
```

`./install.sh` (no flags) runs `sudo apt-get` and builds Picom, and `--restore` rewrites files in `~/.config`. Don't run these without the user's go-ahead. `preview.py` needs `xserver-xephyr` and `imagemagick`; it only talks to its own nested display (`:90`–`:99`) and writes logs/screenshots to the git-ignored `.preview/`.

## Architecture

Debian 12 desktop bundle (i3 + Polybar + Rofi + Dunst + Picom 13). All user-facing text is Ukrainian; keep that when editing menus, notifications and docs.

- `config/` mirrors `~/.config/`: `i3/config`, `i3/autumn/{desktop.py,audio.py,dunstrc,picom.conf,wallpaper.png}`, `polybar/autumn.ini`, `rofi/autumn.rasi`. Configs reference scripts via `~/.config/...` paths, so the repo copy is not live until installed (`preview.py` rewrites `~/.config/` to the repo's `config/` for its sandbox).
- `config/i3/autumn/desktop.py` — single CLI entry point (subcommands such as `menu`, `help`, `terminal`, `scratchpad`, `lock`, `power`, `keyboard-setup`, `keyboard-next`, `session-start`) invoked from i3 bindings. Contains the `Supervisor` that, per i3 session, owns Polybar, Dunst, Picom, xss-lock and the wallpaper, and tears them down with the session (no global `pkill`). Commands refuse to run outside i3 and use confirmation menus for power/session actions. Keyboard layout cycling (EN → RU → UA) is done through XKB groups, not GNOME.
- `config/i3/autumn/audio.py` — PulseAudio/PipeWire control via `pactl`. `watch-output`/`watch-input` are long-running `pactl subscribe` followers that print status lines for Polybar modules (`tail = true`); other subcommands handle device menus, volume and mute. Device names must never be turned into shell commands.
- `scripts/install_config.py` — installs exactly the allowlist in `FILES` into `~/.config` with a manifest-backed backup in `~/.local/state/i3-autumn/backups/<stamp>/`, atomic copies, rollback on failure, and a guarded `--restore` that refuses if installed files changed since. Rejects symlinks and paths outside the target home. `--target-home` lets tests install into a temp dir.
- `install.sh` — only user-facing installer: validates the bundle, checks Debian 12, installs missing apt packages (`--no-remove`), builds Picom v13 from a pinned commit (`autumn_revision`) into `~/.local/bin/picom-autumn` (copying only the binary, no global autostart), then calls `install_config.py`.

When adding or renaming a config file, update the `FILES` allowlist in `scripts/install_config.py`, the file-presence loop in `install.sh`, and the tests (`restore` validates the allowlist, with a legacy set lacking `picom.conf`).

When changing i3 bindings, keep the key tables in `README.md` and `README.uk.md` in sync. `tests/` uses `unittest`; installer tests use stub apt/build commands and temp homes.
