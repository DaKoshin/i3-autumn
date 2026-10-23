import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("autumn_install", Path(__file__).parents[1] / "scripts/install_config.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.config = self.home / ".config/i3/config"
        self.config.parent.mkdir(parents=True)
        self.config.write_text("original i3 config\n")
        self.config.chmod(0o600)

    def test_install_and_restore_preserve_original_and_unrelated_files(self):
        unrelated = self.home / ".config/i3/untouched.txt"
        unrelated.write_text("leave alone")
        result = installer.install(self.home)
        self.assertEqual(result["installed"], 8)
        self.assertIn("AUTUMN", self.config.read_text())
        backup = Path(result["backup"])
        self.assertEqual((backup / "original/.config/i3/config").read_text(), "original i3 config\n")
        installer.restore(self.home, backup)
        self.assertEqual(self.config.read_text(), "original i3 config\n")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(unrelated.read_text(), "leave alone")
        self.assertFalse((self.home / ".config/polybar/autumn.ini").exists())

    def test_restore_refuses_to_discard_user_edits_before_any_write(self):
        result = installer.install(self.home)
        bar = self.home / ".config/polybar/autumn.ini"
        bar.write_text("user edits")
        before = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, "File changed"):
            installer.restore(self.home, Path(result["backup"]))
        self.assertEqual(bar.read_text(), "user edits")
        self.assertEqual(self.config.read_bytes(), before)

    def test_symlink_is_rejected_before_backups_or_mutations(self):
        link = self.home / ".config/rofi"
        target = self.home / "elsewhere"
        target.mkdir()
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            installer.install(self.home)
        self.assertEqual(self.config.read_text(), "original i3 config\n")
        self.assertFalse((self.home / ".local/state").exists())

    def test_check_does_not_create_files(self):
        result = installer.install(self.home, check=True)
        self.assertEqual(len(result["files"]), 8)
        self.assertFalse((self.home / ".local/state").exists())
        self.assertEqual(self.config.read_text(), "original i3 config\n")

    def test_symlinked_manifest_is_rejected(self):
        result = installer.install(self.home)
        backup = Path(result["backup"])
        manifest = backup / "manifest.json"
        other = self.home / "elsewhere.json"
        manifest.rename(other)
        manifest.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink"):
            installer.restore(self.home, backup)

    def test_restore_failure_rolls_back_previous_changes(self):
        result = installer.install(self.home)
        original_copy = installer.atomic_copy
        fail_once = True

        def copy_with_failure(source, target, mode):
            nonlocal fail_once
            if fail_once and target == self.config:
                fail_once = False
                raise OSError("simulated disk failure")
            return original_copy(source, target, mode)

        with mock.patch.object(installer, "atomic_copy", side_effect=copy_with_failure):
            with self.assertRaisesRegex(OSError, "simulated"):
                installer.restore(self.home, Path(result["backup"]))
        for name in installer.FILES:
            self.assertEqual((self.home / ".config" / name).read_bytes(),
                             (installer.ROOT / "config" / name).read_bytes())
        installer.restore(self.home, Path(result["backup"]))
        self.assertEqual(self.config.read_text(), "original i3 config\n")

    def test_restore_accepts_previous_seven_file_backup(self):
        previous = tuple(name for name in installer.FILES if name != "i3/autumn/picom.conf")
        with mock.patch.object(installer, "FILES", previous):
            result = installer.install(self.home)
        installer.restore(self.home, Path(result["backup"]))
        self.assertEqual(self.config.read_text(), "original i3 config\n")


if __name__ == "__main__":
    unittest.main()
