"""Exercise install.sh with a disposable HOME and no real privileged commands."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PICOM_REVISION = "d87a5ba3af7a9ee3c4e040ee29b2dea7e9e46317"
REQUIRED_COMMANDS = (
    "i3", "i3-msg", "polybar", "rofi", "pactl", "pavucontrol", "setxkbmap",
    "xset", "xss-lock", "i3lock", "xwallpaper",
)
MOCK_COMMANDS = ("sudo", "apt-get", "dpkg-query", "git", "meson", "ninja")


@unittest.skipIf(os.geteuid() == 0, "The installer intentionally refuses root; do not bypass that guard")
class ShellInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="autumn-shell-test-")
        self.addCleanup(self.temporary.cleanup)
        self.sandbox = Path(self.temporary.name)
        self.home = self.sandbox / "home"
        self.bin = self.sandbox / "bin"
        self.builds = self.sandbox / "builds"
        self.log = self.sandbox / "commands.jsonl"
        for directory in (self.home, self.bin, self.builds):
            directory.mkdir()
        # An allowlist PATH prevents any unexpected command from falling through
        # to the real sudo, apt, networking tools, or X session applications.
        for name in ("cat", "dirname", "mkdir", "mktemp", "date", "cp", "install", "mv"):
            executable = shutil.which(name)
            if not executable:
                self.skipTest(f"Required local core utility is missing: {name}")
            (self.bin / name).symlink_to(executable)
        (self.bin / "python3").symlink_to(sys.executable)
        for name in MOCK_COMMANDS + REQUIRED_COMMANDS:
            self.write_executable(self.bin / name, self.mock_program())
        fixture = self.sandbox / "bash-fixture"
        fixture.write_text(textwrap.dedent("""\
            source() {
                if [[ "$1" == /etc/os-release ]]; then
                    ID=debian
                    VERSION_ID=12
                else
                    printf 'Unexpected source in isolated installer test\n' >&2
                    return 97
                fi
            }
        """))
        # Deliberately construct a minimal environment, never copy the caller's
        # environment, real HOME, display, D-Bus address, or credential settings.
        self.environment = {
            "HOME": str(self.home), "PATH": str(self.bin), "TMPDIR": str(self.builds),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "BASH_ENV": str(fixture),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "AUTUMN_TEST_LOG": str(self.log), "AUTUMN_TEST_MISSING": "rofi,meson",
            "AUTUMN_TEST_REVISION": PICOM_REVISION,
        }

    @staticmethod
    def write_executable(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    @staticmethod
    def mock_program():
        return f"#!{sys.executable}\n" + textwrap.dedent("""\
            import json
            import os
            from pathlib import Path
            import sys

            name, args = Path(sys.argv[0]).name, sys.argv[1:]
            with open(os.environ["AUTUMN_TEST_LOG"], "a") as log:
                log.write(json.dumps([name, *args]) + "\\n")
            if name == "dpkg-query":
                missing = os.environ["AUTUMN_TEST_MISSING"].split(",")
                if args[-1] in missing:
                    sys.exit(1)
                print("installed", end="")
            elif name == "sudo":
                if not args or args[0] != "apt-get":
                    sys.exit("Mock sudo permits only the mock apt-get")
                program = str(Path(sys.argv[0]).parent / "apt-get")
                os.execv(program, [program, *args[1:]])
            elif name == "apt-get":
                if not args or args[0] not in ("update", "install"):
                    sys.exit("Unexpected mock apt operation")
            elif name == "git":
                if "clone" in args:
                    Path(args[-1]).mkdir(parents=True)
                elif "rev-parse" in args:
                    print(os.environ["AUTUMN_TEST_REVISION"])
                elif "submodule" not in args:
                    sys.exit("Unexpected mock git operation")
            elif name == "meson":
                if args[0] != "setup":
                    sys.exit("Only a local mock build is allowed")
                (Path(args[1]) / "src").mkdir(parents=True)
            elif name == "ninja":
                if "install" in args:
                    sys.exit("Global install is forbidden in the test")
                binary = Path(args[args.index("-C") + 1]) / "src/picom"
                binary.write_text("#!/bin/sh\\nprintf 'v13\\\\n'\\n")
                binary.chmod(0o755)
            else:
                sys.exit("A live desktop command must never run during installation: " + name)
        """)

    def run_installer(self, *arguments, project=ROOT, expected=0):
        result = subprocess.run(
            ["/bin/bash", str(project / "install.sh"), *map(str, arguments)],
            cwd=self.sandbox, env=self.environment, capture_output=True, text=True,
            timeout=30, check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def home_snapshot(self):
        return {
            str(path.relative_to(self.home)): (stat.S_IMODE(path.stat().st_mode),
                                               path.read_bytes() if path.is_file() else None)
            for path in self.home.rglob("*")
        }

    def seed_config(self):
        config = self.home / ".config/i3/config"
        config.parent.mkdir(parents=True)
        config.write_text("# My previous i3 settings\nfont pango:monospace 11\n")
        config.chmod(0o600)
        unrelated = self.home / ".config/personal-settings.txt"
        unrelated.write_text("Keep this user file\n")
        return config, config.read_bytes(), unrelated

    def backup(self):
        manifests = list((self.home / ".local/state/i3-autumn/backups").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        return manifests[0].parent

    def test_check_leaves_home_unchanged_and_never_requests_privileged_or_build_commands(self):
        self.seed_config()
        before = self.home_snapshot()
        self.run_installer("--check")
        self.assertEqual(self.home_snapshot(), before)
        self.assertEqual(list(self.builds.iterdir()), [])
        self.assertTrue(self.events())
        self.assertEqual({event[0] for event in self.events()}, {"dpkg-query"})

    def test_no_animations_backs_up_and_restore_works_without_config_sources(self):
        config, previous, unrelated = self.seed_config()
        self.run_installer("--no-animations")
        backup = self.backup()
        self.assertEqual(config.read_bytes(), (ROOT / "config/i3/config").read_bytes())
        self.assertEqual((backup / "original/.config/i3/config").read_bytes(), previous)
        self.assertFalse((self.home / ".local/bin/picom-autumn").exists())
        self.assertFalse({"git", "meson", "ninja"} & {event[0] for event in self.events()})
        self.assertTrue(any(event[:2] == ["apt-get", "install"] for event in self.events()))

        # A damaged checkout must still be usable to restore an existing backup.
        incomplete = self.sandbox / "incomplete-checkout"
        (incomplete / "scripts").mkdir(parents=True)
        shutil.copy2(ROOT / "install.sh", incomplete / "install.sh")
        shutil.copy2(ROOT / "scripts/install_config.py", incomplete / "scripts/install_config.py")
        calls_before_restore = self.events()
        self.run_installer("--restore", backup, project=incomplete)
        self.assertEqual(config.read_bytes(), previous)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        self.assertEqual(unrelated.read_text(), "Keep this user file\n")
        self.assertFalse((self.home / ".config/i3/autumn/audio.py").exists())
        self.assertEqual(self.events(), calls_before_restore)

    def test_default_build_replaces_only_local_binary_and_applies_real_config_backend(self):
        target = self.home / ".local/bin/picom-autumn"
        previous = "#!/bin/sh\nprintf 'v9\\n'\n"
        self.write_executable(target, previous)
        self.run_installer()
        self.assertIn("v13", target.read_text())
        self.assertTrue(os.access(target, os.X_OK))
        binary_backups = list((self.home / ".local/state/i3-autumn/binary-backups").glob("*/picom-autumn"))
        self.assertEqual(len(binary_backups), 1)
        self.assertEqual(binary_backups[0].read_text(), previous)
        self.assertEqual((self.home / ".config/i3/config").read_bytes(), (ROOT / "config/i3/config").read_bytes())
        self.backup()
        names = {event[0] for event in self.events()}
        self.assertTrue({"git", "meson", "ninja", "apt-get"} <= names)
        self.assertTrue(all(event[1] == "apt-get" for event in self.events() if event[0] == "sudo"))
        self.assertFalse((self.home / ".config/autostart").exists())
        self.assertEqual([path.name for path in target.parent.iterdir()], ["picom-autumn"])

    def test_unexpected_source_revision_stops_before_binary_or_config_replacement(self):
        config, previous, unrelated = self.seed_config()
        target = self.home / ".local/bin/picom-autumn"
        self.write_executable(target, "#!/bin/sh\nprintf 'v9\\n'\n")
        before = self.home_snapshot()
        self.environment["AUTUMN_TEST_REVISION"] = "untrusted-revision"
        self.run_installer(expected=1)
        self.assertEqual(self.home_snapshot(), before)
        self.assertNotIn("ninja", {event[0] for event in self.events()})


if __name__ == "__main__":
    unittest.main()
