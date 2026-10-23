# Autumn — i3 + Polybar

**English** · [Українська](README.uk.md)

![Autumn desktop preview](docs/screenshot.png)

A dark autumn desktop for Debian 12: warm copper accents, a misty forest wallpaper, a compact bar, Ukrainian-language menus, comfortable tiling and separate control of the audio output and the microphone. Prepared for i3 4.22, Polybar 3.6.3, Rofi 1.7.3, PipeWire/PulseAudio, GNOME Terminal, xss-lock and i3lock. Windows are 15% translucent with a blurred background (Picom 13).

> All user-facing text (menus, notifications, help) is in Ukrainian.

## Getting started

Clone the repository anywhere and run the only installer:

```sh
cd ~/i3-autumn
./install.sh
```

Run it as your normal user. The script calls `sudo` itself to install missing Debian packages, builds the official Picom 13 as a regular user and installs the configuration with a backup. An internet connection is needed to download packages and source code. Enter your password only at the `sudo` prompt in your own terminal.

After the installation, save your work and log out of GNOME in the usual way. On the GDM screen pick your user, choose **i3** in the session menu (the gear icon) and log in. The installer does not end the current session.

Press **Win+C** to open the control centre or **Win+F1** to see the key bindings. The **AUTUMN** button on the bar also opens the control centre.

## Key bindings

| Keys | Action |
| --- | --- |
| Ctrl+Space | Switch back to the previous language (like macOS), also in resize mode |
| Ctrl+Alt+Space | Cycle languages: EN → RU → UA → EN, also in resize mode |
| Win+Enter | Terminal |
| Win+D / Win+Tab | Applications / open windows |
| Win+C / Win+F1 | Control centre / help |
| Win+P | Sound menu |
| Win+Ctrl+P | Audio output |
| Win+Ctrl+Shift+P | Microphone |
| Win+arrows | Focus a window |
| Win+Shift+arrows | Move a window |
| Win+H / Win+V | Split horizontally / vertically |
| Win+W / Win+S / Win+E | Tabbed / stacking / toggle split direction |
| Win+F | Fullscreen |
| Win+R, arrows, Enter | Resize a window |
| Win+Shift+T / Win+T | Floating window / switch focus between floating and tiled |
| Win+G | Gaps between windows for the current workspace |
| Win+1…8 | Workspaces |
| Win+Ctrl+1…8 | Send a window without following it |
| Win+Shift+1…8 | Send a window and follow it |
| Win+B | Previous workspace |
| Win+F12 | Drop-down terminal |
| Win+Shift+minus / Win+minus | Hide to the scratchpad / show |
| Win+Q | Close a window |
| Win+Ctrl+L | Lock the screen |
| Win+Shift+E | Session menu: lock, sleep, log out, GNOME, power |
| Print | Select a screen region in Flameshot |
| Win+Shift+C / Win+Shift+R | Reload the config / restart i3 keeping windows |

Windows can be dragged with the mouse while holding Win; the right button with Win resizes them. The old j/k/l/; navigation keys are kept. Urgent windows no longer steal focus automatically. The outer gap is 16 px in normal mode, in tabs and for a single window; the gap between neighbouring windows is 12 px. Fullscreen uses the whole screen.

## Bar and audio

- **AUTUMN**: left click — control centre, right click — applications.
- Workspace numbers: click to switch; scroll to cycle.
- Date: click to change the display format.
- **NET** opens the network connection settings; available Wi-Fi networks are in the NetworkManager tray.
- **VOL**: left click — choose output; middle click — mute; right click — full mixer; wheel — volume in 5% steps, up to 100%.
- **MIC**: left click — choose microphone; middle or right click — mute. ON means the microphone is not muted, not that an application is recording.
- **EN/RU/UA** shows the current language; change it with Ctrl+Space (previous language), Ctrl+Alt+Space (cycle) or by clicking the indicator.
- **SESSION**: left click — session menu, right click — help.

Choosing a device changes the default output/input and moves the streams that are already active. Capturing system sound through monitor sources stays in place. The script never unmutes a muted microphone on its own. HDMI/analog profiles and per-application settings are handled in the **full mixer**. A new connection that has not yet created an audio device in PipeWire must be activated there first.

Volume, mute, microphone and default-device changes are updated from `pactl subscribe` events, including changes made from another mixer. Polybar reads the stream through `tail = true`; the three-second polling is gone. Identical values are not printed again and service-client connection events are ignored. The subscription is restored after the sound server restarts.

## GNOME and screen locking

The **SESSION → Switch to GNOME** menu item shows an explanation and asks for confirmation. After logging out pick GNOME on the GDM screen. Switching ends the current i3 session, so save your documents first. GNOME → i3: log out of GNOME normally and pick i3 in GDM.

GNOME settings are not changed. In the tested setup GNOME already had English, Ukrainian, Russian and Win+Space; the GNOME order is left as EN → UA → RU. i3 uses EN → RU → UA. The shortcuts are grabbed by i3 itself and the script switches the XKB group. If a background input manager left only one layout, the next switch restores all three groups. These commands refuse to run outside i3.

The screen locks after 10 minutes of inactivity through xss-lock/i3lock and before sleep from the menu. Automatic sleep is not added. The bars, notifications and helper processes belong to the supervisor of the current i3 session and are closed together with it. Restarting the bars does not run a global `pkill`. The bundle does not change GNOME dconf, SSH or the display manager and does not add Picom to the global autostart. Debian packages may install their own default services and autostart entries.

## Privacy

[AGENTS.md](AGENTS.md) forbids agents to read SSH/GPG keys, tokens, keyrings, browser profiles, `.env`, shell history and the full environment; matching exclusions are added to `.gitignore`. The bundled widgets run locally, without telemetry, network requests or third-party plugin downloads. Audio device names are never turned into shell commands.

**AGENTS.md contains rules for agents working on this project; it is not OS-level isolation.** It does not take file access away from arbitrary plugins or applications running as your user. Private keys and secret directories were not read or copied while preparing this work.

## Installation and restore

All normal actions go through `install.sh`:

```sh
./install.sh --check          # Check the bundle and dependencies without changes
./install.sh                  # Packages, Picom 13, configuration
./install.sh --no-animations  # Packages and configuration without building Picom
```

The script supports Debian 12. It installs missing programs, fonts, a graphical authentication agent and, if needed, the tools to build Picom. An existing PipeWire or PulseAudio is kept; if there is neither, PipeWire/WirePlumber is installed. GNOME and GDM are not reinstalled. Apt runs with package removal forbidden.

Then the internal module `scripts/install_config.py` applies eight explicitly listed files: `~/.config/i3/config`, five files in `~/.config/i3/autumn/`, `~/.config/polybar/autumn.ini` and `~/.config/rofi/autumn.rasi`. Old `polybar/config`, `rofi/config.rasi`, wallpapers and shell startup files stay where they are. The configuration is validated before the packages are installed if Python is already available.

The originals of the changed files are stored in `~/.local/state/i3-autumn/backups/<date-time>/`. The exact path is printed after the installation. To restore:

```sh
./install.sh --restore ~/.local/state/i3-autumn/backups/DATE-TIME
```

Replace `DATE-TIME` with the directory printed by the installer. If the files were changed after the installation, the restore stops so that those edits are not lost. Backups are never deleted automatically. The restore covers configuration only; installed packages and the local Picom stay. Log in to i3 again afterwards.

Layout: `config/` — configuration, desktop scripts and wallpaper; `scripts/` — internal installer module and the optional terminal profile; `tests/` — tests; `preview.py` and `.preview/` — preview rendering; `docs/` — screenshot; `AGENTS.md` and `CLAUDE.md` — rules and notes for agents; `LICENSE` — MIT; `README.uk.md` — Ukrainian version of this file. The installer computes paths from its own location, so the project folder can be moved.

## Animations

`~/.config/i3/autumn/picom.conf` defines a 200 ms scale-in on open, a 220 ms close shrinking to 90%, a vertical slide for individual windows when switching workspaces, soft shadows and 8 px corners. Focus changes, including i3 tabs (Win+W), get a smooth 180 ms transition. Windows are 15% translucent (opacity 0.85) with a blurred background (`dual_kawase`); an unfocused window is slightly more transparent (0.83), and that difference is what triggers the transition: i3 keeps the tabs mapped and raises the active one, so `show`/`hide` alone do not fire. Layout changes (Win+W tabs, Win+E split) are animated for 160 ms (Picom's geometry animation, which also applies to dragging and resizing with the mouse). Bars, Rofi menus, notifications and the screen locker are excluded from the effects.

GLX/VSync is used with no fixed 60 Hz limit. This does not change the monitor's resolution or refresh rate. The compositor is not started for GNOME.

Open **Win+C → Анімації** (Animations) to control the effects. On a system with a missing or old compositor the supervisor skips starting it; the regular installer builds the required version.

The installer builds the [official Picom v13](https://github.com/yshui/picom/releases/tag/v13) from the pinned commit `d87a5ba3af7a9ee3c4e040ee29b2dea7e9e46317` into `~/.local/bin/picom-autumn`. Dependencies are installed through Debian apt with sudo; the compositor itself is built as a regular user. A private modern libconfig is built through the pinned upstream wrap without replacing the system library. No global autostart is added.

The build is part of the normal `./install.sh` run. The `--no-animations` flag only skips the build: if a modern Picom is already installed, the supervisor can still start it. Effects can be turned off in the animations menu.

After a successful installation log in to i3 again to load the updated supervisor. The script does not end the session. If the compositor crashes, it reports it and does not create a restart loop. The animations menu has an item to go back to a no-effects mode.

**Verification:** all automated tests pass; i3 and Bash syntax is checked. The real Picom v13 was started in a nested, isolated X11 session: the configuration was read, the log shows the close and focus-change animations starting, and the image has intermediate frames of the tab transition. The settings follow the [official v13 manual](https://raw.githubusercontent.com/yshui/picom/v13/man/picom.1.adoc). The installer integration tests use stub apt/build commands; a full package reinstall was not repeated.

## Layouts and keys

i3 uses the physical key positions of the first layout and activates the bindings in every group. Each individual command was not verified separately. Shortcuts inside applications depend on the applications themselves.

## Checks and known issues

The syntax was checked with a local i3 4.22; Polybar/Rofi and switching between the three languages were run in a nested, isolated Xephyr X11 session. The [preview screenshot](docs/screenshot.png) shows the real wallpaper, bar and menu styling with demo entries. The layouts actually went through the group cycle 0 → 1 → 2 → 0.

The automated tests cover audio routing, monitor sources, device disconnects, menu cancellation, volume limits, command protection outside i3, power confirmation, lifecycle, backups and restore. Live switching of your audio streams, locking, sleep, rebooting and logging out of the current GNOME session were deliberately not performed.

```sh
python3 -m unittest discover -s tests -v
i3 -C -c config/i3/config
python3 preview.py
```

The optional `preview.py` additionally needs `xserver-xephyr` and `imagemagick`. The installer includes the desktop dependencies but not these development tools.

The old config had Win+Space for focus, a missing `picom`, power commands through a missing `doas`, an invalid Polybar hex colour and a global `pkill polybar`. These places were replaced. The Telegram and Guake autostart of the old i3 config was removed; add your own autostart and personal settings to `~/.config/i3/local.conf` (the main config includes it; the installer never creates or overwrites it). Applications are available through the menu and the drop-down terminal through Win+F12.

The composition uses opaque surfaces and works without picom. The wallpaper was created with imagegen; the source file is 1672×941 px and is scaled to the monitor. The settings follow the [official i3 user guide](https://i3wm.org/docs/userguide.html), the [Polybar xkeyboard documentation](https://github.com/polybar/polybar/wiki/Module:-xkeyboard) and the [GNOME keyboard layouts help](https://help.gnome.org/gnome-help/keyboard-layouts.html).

## Terminal theme (optional)

gnome-terminal colours are stored in dconf, so the «Autumn» profile is installed with a separate, explicit command rather than through `install.sh`:

```sh
python3 scripts/terminal_profile.py          # add the profile, the default one is untouched
python3 scripts/terminal_profile.py remove   # remove the profile
```

`Mod+Return` and F12 open the terminal with this profile (`--profile=Autumn`); if it is not installed, gnome-terminal uses the default one.

## Personal settings

The main i3 config includes `~/.config/i3/local.conf`. Put your own autostart (`exec ...`) and bindings there. The installer never creates or overwrites this file.

## License

[MIT](LICENSE).
