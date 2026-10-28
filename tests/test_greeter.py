"""Greeter logic checks; no LightDM or display needed."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "autumn_greeter", Path(__file__).parents[1] / "greeter/autumn_greeter.py")
greeter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(greeter)

SESSIONS = [("gnome", "GNOME"), ("i3", "i3")]


class GreeterTests(unittest.TestCase):
    def test_remembered_session_wins(self):
        self.assertEqual(greeter.pick_session(SESSIONS, "gnome"), "gnome")

    def test_i3_is_default(self):
        self.assertEqual(greeter.pick_session(SESSIONS), "i3")
        self.assertEqual(greeter.pick_session(SESSIONS, "gone"), "i3")

    def test_first_session_fallback_and_empty(self):
        self.assertEqual(greeter.pick_session([("a", "A")]), "a")
        self.assertIsNone(greeter.pick_session([]))

    def test_system_users_are_hidden(self):
        users = [("root", "root", 0), ("me", "Me", 1000)]
        self.assertEqual(greeter.visible_users(users), [("me", "Me", 1000)])

    def test_demo_rejects_wrong_password_and_never_starts_session(self):
        backend = greeter.DemoBackend()
        results = []
        backend.start(lambda _t: None, lambda _m: None, results.append)
        backend.authenticate("demo")
        backend.respond("wrong")
        self.assertEqual(results, [False])
        self.assertEqual(backend.log, [])

    def test_demo_accepts_demo_password(self):
        backend = greeter.DemoBackend()
        results = []
        backend.start(lambda _t: None, lambda _m: None, results.append)
        backend.authenticate("demo")
        backend.respond(greeter.DEMO_PASSWORD)
        self.assertEqual(results, [True])


if __name__ == "__main__":
    unittest.main()
