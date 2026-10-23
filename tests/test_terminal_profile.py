import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "terminal_profile", Path(__file__).resolve().parents[1] / "scripts/terminal_profile.py")
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


class TerminalProfileTests(unittest.TestCase):
    def test_profile_has_sixteen_colors_and_does_not_follow_the_gtk_theme(self):
        text = profile.profile_text()
        self.assertEqual(text.count("'rgb("), 16 + 6)
        self.assertIn("use-theme-colors=false", text)
        self.assertIn(f"[:{profile.UUID}]", text)

    def test_install_appends_profile_and_keeps_existing_ones(self):
        calls = []

        def fake(argv, **kwargs):
            calls.append(argv)
            return done("['old-profile']\n") if argv[1] == "get" else done()

        with patch.object(profile, "run", side_effect=fake), patch("builtins.print"):
            profile.install()
        self.assertIn(["gsettings", "set", *profile.LIST_SCHEMA, f"['old-profile', '{profile.UUID}']"], calls)
        self.assertFalse(any("default" in " ".join(call) for call in calls))

    def test_remove_drops_only_its_own_profile(self):
        calls = []

        def fake(argv, **kwargs):
            calls.append(argv)
            return done(f"['old-profile', '{profile.UUID}']\n") if argv[1] == "get" else done()

        with patch.object(profile, "run", side_effect=fake), patch("builtins.print"):
            profile.remove()
        self.assertIn(["gsettings", "set", *profile.LIST_SCHEMA, "['old-profile']"], calls)
        self.assertIn(["dconf", "reset", "-f", f"{profile.PROFILES}:{profile.UUID}/"], calls)

    def test_unavailable_gsettings_stops_before_any_write(self):
        with patch.object(profile, "run", return_value=done(code=1)) as run:
            with self.assertRaises(SystemExit):
                profile.install()
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
