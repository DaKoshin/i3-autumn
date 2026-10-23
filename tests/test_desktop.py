"""Behavior checks with all desktop/process operations mocked."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location(
    "desktop", Path(__file__).parents[1] / "config/i3/autumn/desktop.py")
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)


class GuardTests(unittest.TestCase):
    def test_every_action_is_blocked_without_i3(self):
        for action in ("menu", "power", "help", "terminal", "scratchpad", "lock", "session-start", "bars", "motion",
                       "keyboard-setup", "keyboard-next", "keyboard-prev"):
            with self.subTest(action=action), patch.object(desktop.Connection, "current", side_effect=desktop.DesktopError("not i3")), \
                    patch.object(desktop, "run") as run, patch.object(desktop, "detached") as launch, \
                    patch.object(desktop, "runtime_dir") as runtime, patch("sys.stderr"), \
                    patch.object(desktop.shutil, "which", return_value=None):
                self.assertEqual(desktop.main([action]), 1)
                run.assert_not_called()
                launch.assert_not_called()
                runtime.assert_not_called()

    def test_socket_is_verified_with_live_i3_version(self):
        results = [subprocess.CompletedProcess([], 0, "/run/user/1000/i3/ipc-socket.42\n", ""),
                   subprocess.CompletedProcess([], 0, '{"major": 4, "minor": 22}', "")]
        with patch.object(desktop, "run", side_effect=results) as run:
            connection = desktop.Connection.current()
            self.assertEqual(connection.socket, "/run/user/1000/i3/ipc-socket.42")
            self.assertEqual(run.call_args.args[0], ["i3-msg", "-s", connection.socket, "-t", "get_version"])

    def test_stale_socket_does_not_authorize_actions(self):
        results = [subprocess.CompletedProcess([], 0, "/tmp/stale-socket", ""),
                   subprocess.CompletedProcess([], 1, "", "connection refused")]
        with patch.object(desktop, "run", side_effect=results):
            with self.assertRaises(desktop.DesktopError):
                desktop.Connection.current()


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.state = Path(home.name) / "state/keyboard-group"
        self.previous = Path(home.name) / "state/keyboard-previous"
        for name, path in (("KEYBOARD_GROUP", self.state), ("KEYBOARD_PREVIOUS", self.previous)):
            patcher = patch.object(desktop, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def xlib(self, group=0, error=0):
        library = MagicMock()
        library.XOpenDisplay.return_value = 123

        def state(_display, _device, result):
            result[0] = bytes([group])
            return error

        library.XkbGetState.side_effect = state
        library.XkbLockGroup.return_value = 1
        return library

    def test_group_cycle_uses_xkb_without_replacing_a_valid_keymap(self):
        for group, following in ((0, 1), (1, 2), (2, 0)):
            library = self.xlib(group)
            with self.subTest(group=group), patch.object(desktop.ctypes, "CDLL", return_value=library), \
                    patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0, "layout: us,ru,ua\n")), \
                    patch.object(desktop, "configure_keyboard") as configure:
                desktop.next_layout()
            library.XkbLockGroup.assert_called_once_with(123, 0x0100, following)
            library.XCloseDisplay.assert_called_once_with(123)
            configure.assert_not_called()

    def switch_back(self, group):
        library = self.xlib(group)
        with patch.object(desktop.ctypes, "CDLL", return_value=library), \
                patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0, "layout: us,ru,ua\n")):
            desktop.previous_layout()
        return library.XkbLockGroup.call_args.args[2]

    def test_previous_layout_toggles_between_the_last_two_languages(self):
        # EN -> RU -> UA by cycling, then Ctrl+Space jumps back to RU and again to UA.
        for group in (0, 1):
            with patch.object(desktop.ctypes, "CDLL", return_value=self.xlib(group)), \
                    patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0, "layout: us,ru,ua\n")):
                desktop.next_layout()
        self.assertEqual(self.state.read_text(), "2\n")
        self.assertEqual(self.switch_back(2), 1)
        self.assertEqual(self.state.read_text(), "1\n")
        self.assertEqual(self.switch_back(1), 2)

    def test_previous_layout_without_history_moves_to_next(self):
        self.assertEqual(self.switch_back(0), 1)
        self.state.unlink()
        self.previous.write_text("1\n")
        self.assertEqual(self.switch_back(1), 2)

    def test_last_layout_is_saved_and_restored_after_keymap_reset(self):
        with patch.object(desktop.ctypes, "CDLL", return_value=self.xlib(1)), \
                patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0, "layout: us,ru,ua\n")):
            desktop.next_layout()
        self.assertEqual(self.state.read_text(), "2\n")
        library = self.xlib(0)
        with patch.object(desktop.ctypes, "CDLL", return_value=library), \
                patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0)):
            desktop.configure_keyboard()
        library.XkbLockGroup.assert_called_once_with(123, 0x0100, 2)

    def test_corrupt_saved_layout_falls_back_to_first_group(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("junk")
        library = self.xlib(0)
        with patch.object(desktop.ctypes, "CDLL", return_value=library), \
                patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0)):
            desktop.configure_keyboard()
        library.XkbLockGroup.assert_not_called()

    def test_single_group_map_is_repaired_before_switching(self):
        library = self.xlib()
        with patch.object(desktop.ctypes, "CDLL", return_value=library), \
                patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0, "layout: us\n")), \
                patch.object(desktop, "configure_keyboard") as configure:
            desktop.next_layout()
        configure.assert_called_once_with()
        library.XkbLockGroup.assert_called_once_with(123, 0x0100, 1)

    def test_failed_xkb_query_closes_display_without_switching(self):
        library = self.xlib(error=1)
        with patch.object(desktop.ctypes, "CDLL", return_value=library), \
                patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0, "layout: us,ru,ua\n")):
            with self.assertRaises(desktop.DesktopError):
                desktop.next_layout()
        library.XkbLockGroup.assert_not_called()
        library.XCloseDisplay.assert_called_once_with(123)


class MenuTests(unittest.TestCase):
    def test_cancel_is_the_default_confirmation(self):
        with patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], 0, "0\n", "")) as run:
            self.assertFalse(desktop.confirm("Вимкнути", "Збережіть документи"))
            argv = run.call_args.args[0]
            self.assertEqual(argv[argv.index("-selected-row") + 1], "0")
            self.assertEqual(argv[argv.index("-config") + 1], str(desktop.THEME))
            self.assertEqual(run.call_args.kwargs["input"].splitlines()[0], "Скасувати")

    def test_escape_invalid_and_cancel_input_do_not_confirm(self):
        for output, status in (("", 1), ("-1", 0), ("99", 0), ("1; reboot", 0), ("0", 0)):
            with self.subTest(output=output), patch.object(desktop, "run", return_value=subprocess.CompletedProcess([], status, output, "")):
                self.assertFalse(desktop.confirm("Вимкнути", ""))

    def test_cancel_power_does_not_execute_any_action(self):
        for action in (2, 3, 4, 5, 6):
            connection = MagicMock()
            with self.subTest(action=action), patch.object(desktop, "choose", return_value=action), \
                    patch.object(desktop, "confirm", return_value=False), patch.object(desktop, "run") as run, \
                    patch.object(desktop, "lock_screen") as lock:
                desktop.power(connection)
                connection.command.assert_not_called()
                run.assert_not_called()
                lock.assert_not_called()

    def test_gnome_selection_only_exits_i3_after_confirmation(self):
        connection = MagicMock()
        connection.alive.return_value = True
        with patch.object(desktop, "choose", return_value=4), patch.object(desktop, "confirm", return_value=True), \
                patch.object(desktop, "run") as run:
            desktop.power(connection)
            connection.command.assert_called_once_with("exit")
            run.assert_not_called()

    def test_suspend_is_cancelled_when_lock_fails(self):
        connection = MagicMock()
        with patch.object(desktop, "choose", return_value=2), patch.object(desktop, "confirm", return_value=True), \
                patch.object(desktop, "lock_screen", side_effect=desktop.DesktopError("lock failed")), patch.object(desktop, "run") as run:
            with self.assertRaises(desktop.DesktopError):
                desktop.power(connection)
            run.assert_not_called()


class LifecycleTests(unittest.TestCase):
    def test_startup_failure_cleans_all_previously_spawned_children(self):
        with tempfile.TemporaryDirectory() as folder:
            supervisor = desktop.Supervisor(MagicMock(), Path(folder))
            first, second = MagicMock(), MagicMock()
            supervisor.children = [first, second]
            with patch.object(supervisor, "configure", side_effect=desktop.DesktopError("setup failed")), \
                    patch.object(desktop, "stop_owned") as stop, patch.object(desktop.signal, "signal"):
                with self.assertRaises(desktop.DesktopError):
                    supervisor.run()
                self.assertEqual([call.args[0] for call in stop.call_args_list], [second, first])

    def test_repeated_session_start_requests_bar_refresh_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            with desktop.open_lock(runtime / "supervisor.lock") as held:
                desktop.fcntl.flock(held, desktop.fcntl.LOCK_EX | desktop.fcntl.LOCK_NB)
                supervisor = desktop.Supervisor(MagicMock(), runtime)
                with patch.object(supervisor, "configure") as configure:
                    supervisor.run()
                    configure.assert_not_called()
                self.assertTrue((runtime / "bars.request").is_file())

    def test_primary_monitor_is_only_tray_and_restart_stops_owned_bars(self):
        connection = MagicMock()
        connection.request.return_value = [{"name": "DP-1", "active": True},
                                          {"name": "eDP-1", "active": True, "primary": True},
                                          {"name": "HDMI-1", "active": False}]
        supervisor = desktop.Supervisor(connection, Path("/unused"))
        previous = MagicMock()
        other_child = MagicMock()
        supervisor.bars = [previous]
        supervisor.children = [previous, other_child]
        observed = []

        def spawn(argv):
            observed.append((argv, os.environ.get("AUTUMN_MONITOR"), os.environ.get("AUTUMN_TRAY")))
            return MagicMock()

        with patch.object(desktop, "stop_owned") as stop, patch.object(supervisor, "spawn", side_effect=spawn):
            supervisor.restart_bars()
            stop.assert_called_once_with(previous)
        self.assertEqual([row[1:] for row in observed], [("DP-1", "none"), ("eDP-1", "right")])
        self.assertEqual(observed[0][0], ["polybar", "--config=" + str(desktop.BAR_CONFIG), "autumn"])
        self.assertIn(other_child, supervisor.children)

    def test_exited_child_is_never_signalled_by_reused_pid(self):
        process = MagicMock()
        process.poll.return_value = 0
        with patch.object(desktop.os, "killpg") as kill:
            desktop.stop_owned(process)
            kill.assert_not_called()

    def test_existing_scratchpad_is_reused(self):
        connection = MagicMock()
        connection.request.return_value = {"nodes": [], "floating_nodes": [
            {"id": 123, "window_properties": {"class": "AutumnScratchpad"}}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(desktop, "runtime_dir", return_value=Path(folder)), \
                patch.object(desktop, "detached") as launch:
            pending = Path(folder) / "scratch.pending"
            pending.write_text(str(desktop.time.monotonic()))
            desktop.scratchpad(connection)
            connection.command.assert_called_once_with("[con_id=123] scratchpad show")
            launch.assert_not_called()
            self.assertFalse(pending.exists())

    def test_recent_slow_scratchpad_launch_is_not_duplicated(self):
        connection = MagicMock()
        connection.request.side_effect = [{"nodes": [], "floating_nodes": []},
                                          {"id": 321, "window_properties": {"class": "AutumnScratchpad"}}]
        with tempfile.TemporaryDirectory() as folder, patch.object(desktop, "runtime_dir", return_value=Path(folder)), \
                patch.object(desktop, "detached") as launch, patch.object(desktop.shutil, "which", return_value="/usr/bin/gnome-terminal"):
            pending = Path(folder) / "scratch.pending"
            pending.write_text(str(desktop.time.monotonic()))
            desktop.scratchpad(connection)
            launch.assert_not_called()
            connection.command.assert_called_once_with("[con_id=321] floating enable, move scratchpad, scratchpad show")
            self.assertFalse(pending.exists())

    def test_help_matches_unreserved_space_bindings(self):
        help_text = "\n".join(desktop.HELP)
        self.assertIn("Win + T ", help_text)
        self.assertIn("Win + Shift + T ", help_text)
        self.assertIn("Win + Ctrl + 1…8", help_text)
        self.assertIn("Ctrl + Space", help_text)
        self.assertNotIn("Win + Space", help_text)
        self.assertNotIn("Shift + Space", help_text)
        self.assertNotIn("1…0", help_text)

    def test_private_runtime_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "target"
            target.mkdir()
            link = Path(folder) / "lock"
            link.symlink_to(target / "other")
            with self.assertRaises(OSError):
                desktop.open_lock(link)


class PicomTests(unittest.TestCase):
    def test_version_probe_prefers_local_and_rejects_old_binaries_without_x(self):
        for local, system, expected in (("v13", "v14", "/local/picom-autumn"),
                                        ("v9", "picom v13.1", "/usr/bin/picom"),
                                        ("v9", "v9.1", None)):
            with self.subTest(local=local, system=system), \
                    patch.object(desktop.shutil, "which", side_effect=["/local/picom-autumn", "/usr/bin/picom"]), \
                    patch.object(desktop, "run", side_effect=[subprocess.CompletedProcess([], 0, local, ""),
                                                              subprocess.CompletedProcess([], 0, system, "")]) as run:
                self.assertEqual(desktop.picom_program(), expected)
                self.assertTrue(all(call.args[0][-1] == "--version" for call in run.call_args_list))
                self.assertEqual(run.call_args_list[0].args[0], ["/local/picom-autumn", "--version"])
                self.assertEqual(run.call_count, 1 if expected == "/local/picom-autumn" else 2)
        with patch.object(desktop.shutil, "which", return_value=None), patch.object(desktop, "run") as run:
            self.assertIsNone(desktop.picom_program())
            run.assert_not_called()

    def test_missing_picom_is_nonfatal_and_creates_no_persistent_preference(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            marker = runtime / "persistent/motion-disabled"
            supervisor = desktop.Supervisor(MagicMock(), runtime)
            with patch.object(desktop, "MOTION_DISABLED", marker), \
                    patch.object(desktop, "picom_program", return_value=None), \
                    patch.object(desktop, "detached") as launch, patch.object(desktop, "notify") as notify:
                supervisor.apply_motion()
            launch.assert_not_called()
            notify.assert_not_called()
            self.assertFalse(marker.parent.exists())
            self.assertEqual((runtime / "motion.status").read_text(), "unavailable")

    def test_disable_stops_only_owned_compositor_and_preserves_other_children(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            marker = runtime / "motion-disabled"
            marker.touch()
            supervisor = desktop.Supervisor(MagicMock(), runtime)
            compositor, bar = MagicMock(), MagicMock()
            supervisor.compositor = compositor
            supervisor.children = [bar, compositor]
            with patch.object(desktop, "MOTION_DISABLED", marker), patch.object(desktop, "stop_owned") as stop, \
                    patch.object(desktop, "picom_program") as probe:
                supervisor.apply_motion()
            stop.assert_called_once_with(compositor)
            probe.assert_not_called()
            self.assertEqual(supervisor.children, [bar])
            self.assertIsNone(supervisor.compositor)
            self.assertEqual((runtime / "motion.status").read_text(), "disabled")

    def test_startup_checks_child_before_claiming_enabled_and_reports_failure(self):
        for exit_status in (None, 1):
            with self.subTest(exit_status=exit_status), tempfile.TemporaryDirectory() as folder:
                runtime = Path(folder)
                child = MagicMock()
                child.poll.return_value = exit_status
                supervisor = desktop.Supervisor(MagicMock(), runtime)
                with patch.object(desktop, "MOTION_DISABLED", runtime / "disabled"), \
                        patch.object(desktop, "picom_program", return_value="/local/picom-autumn"), \
                        patch.object(desktop, "detached", return_value=child) as launch, \
                        patch.object(desktop.time, "sleep"), patch.object(desktop, "notify") as notify:
                    supervisor.apply_motion(announce=True)
                    supervisor.check_motion()
                launch.assert_called_once_with(["/local/picom-autumn", "--config", str(desktop.PICOM_CONFIG)])
                child.poll.assert_called()
                self.assertEqual((runtime / "motion.status").read_text(), "enabled" if exit_status is None else "failed")
                notify.assert_called_once()
                self.assertEqual("увімкнено" in notify.call_args.args[0], exit_status is None)

    def test_crashed_compositor_waits_for_explicit_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            supervisor = desktop.Supervisor(MagicMock(), runtime)
            crashed, replacement = MagicMock(), MagicMock()
            crashed.poll.return_value = 1
            replacement.poll.return_value = None
            supervisor.children = [crashed]
            supervisor.compositor = crashed
            (runtime / "motion.status").write_text("enabled")
            with patch.object(desktop, "MOTION_DISABLED", runtime / "disabled"), \
                    patch.object(desktop, "picom_program", return_value="/local/picom-autumn"), \
                    patch.object(desktop, "detached", return_value=replacement) as launch, \
                    patch.object(desktop.time, "sleep"), patch.object(desktop, "notify") as notify:
                supervisor.check_motion()
                supervisor.check_motion()
                launch.assert_not_called()
                notify.assert_called_once()
                supervisor.apply_motion(announce=True)
            self.assertEqual(supervisor.children, [replacement])
            self.assertEqual((runtime / "motion.status").read_text(), "enabled")

    def test_preferences_change_only_after_explicit_choice_and_request_supervisor(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            marker = runtime / "persistent/motion-disabled"
            connection = MagicMock()
            connection.alive.return_value = True
            with patch.object(desktop, "MOTION_DISABLED", marker), \
                    patch.object(desktop, "runtime_dir", return_value=runtime), \
                    patch.object(desktop, "picom_program", return_value="/local/picom-autumn"), \
                    patch.object(desktop, "choose", side_effect=[None, 2, 1]):
                desktop.motion(connection)
                self.assertFalse(marker.parent.exists())
                self.assertFalse((runtime / "motion.request").exists())
                desktop.motion(connection)
                self.assertTrue(marker.is_file())
                self.assertTrue((runtime / "motion.request").is_file())
                desktop.motion(connection)
                self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
