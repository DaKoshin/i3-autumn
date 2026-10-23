"""No live audio calls: cover menu races, stream routing, and volume bounds."""

import importlib.util
import json
from pathlib import Path
import subprocess
import contextlib
import io
import os
import unittest
from unittest.mock import MagicMock, patch


spec = importlib.util.spec_from_file_location(
    "autumn_audio", Path(__file__).resolve().parents[1] / "config/i3/autumn/audio.py"
)
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


def device(index, name, *, monitor=None, volume=42, mute=False):
    return {
        "index": index, "name": name, "description": name,
        "monitor_of_sink": monitor, "mute": mute,
        "volume": {"front-left": {"value_percent": f"{volume}%"}},
    }


class AudioTests(unittest.TestCase):
    def test_output_selection_sets_default_and_moves_existing_playback(self):
        speakers, headset = device(1, "speakers"), device(2, "headset")
        with patch.object(audio, "devices", side_effect=[[speakers, headset], [speakers, headset]]), \
             patch.object(audio, "choose", return_value=1), \
             patch.object(audio, "list_items", return_value=[{"index": 11}, {"index": 12}]), \
             patch.object(audio, "pactl", return_value="speakers") as command:
            audio.select_device("output")
        self.assertEqual(command.call_args_list, [
            unittest.mock.call("get-default-sink"),
            unittest.mock.call("--", "set-default-sink", "headset"),
            unittest.mock.call("move-sink-input", "11", "2"),
            unittest.mock.call("move-sink-input", "12", "2"),
        ])

    def test_input_choice_filters_monitors_and_preserves_monitor_capture(self):
        old, new = device(1, "internal mic"), device(2, "USB mic")
        monitor = device(3, "speaker.monitor", monitor=0)
        streams = [{"index": 21, "source": 1}, {"index": 22, "source": 3},
                   {"index": 23, "source": 999}, {"index": "not-an-index", "source": 1}]
        with patch.object(audio, "devices", return_value=[old, new, monitor]), \
             patch.object(audio, "choose", return_value=1) as choose, \
             patch.object(audio, "list_items", return_value=streams), \
             patch.object(audio, "pactl", return_value="internal mic") as command:
            audio.select_device("input")
        self.assertEqual(len(choose.call_args.args[1]), 2)
        self.assertEqual(command.call_args_list, [
            unittest.mock.call("get-default-source"),
            unittest.mock.call("--", "set-default-source", "USB mic"),
            unittest.mock.call("move-source-output", "21", "2"),
        ])

    def test_cancel_does_not_mutate_audio(self):
        with patch.object(audio, "devices", return_value=[device(1, "speakers")]), \
             patch.object(audio, "choose", return_value=None), \
             patch.object(audio, "pactl", return_value="speakers") as command, \
             patch.object(audio, "list_items") as listing:
            audio.select_device("output")
        command.assert_called_once_with("get-default-sink")
        listing.assert_not_called()

    def test_disappeared_device_does_not_mutate_audio(self):
        with patch.object(audio, "devices", side_effect=[[device(1, "headset")], []]), \
             patch.object(audio, "choose", return_value=0), \
             patch.object(audio, "pactl", return_value="headset") as command:
            with self.assertRaises(audio.AudioError):
                audio.select_device("output")
        command.assert_called_once_with("get-default-sink")

    def test_reappeared_device_uses_current_index(self):
        with patch.object(audio, "devices", side_effect=[[device(1, "headset")], [device(5, "headset")]]), \
             patch.object(audio, "choose", return_value=0), \
             patch.object(audio, "list_items", return_value=[{"index": 11}]), \
             patch.object(audio, "pactl", return_value="headset") as command:
            audio.select_device("output")
        self.assertEqual(command.call_args, unittest.mock.call("move-sink-input", "11", "5"))

    def test_volume_caps_at_100_and_zero_without_unmuting(self):
        for starting, delta, expected in [(98, 5, "100%"), (140, 5, "100%"), (2, -5, "0%")]:
            with self.subTest(starting=starting), \
                 patch.object(audio, "current_device", return_value=device(3, "sink", volume=starting, mute=True)), \
                 patch.object(audio, "pactl") as command:
                audio.change_volume(delta)
                command.assert_called_once_with("set-sink-volume", "3", expected)

    def test_input_switch_does_not_unmute_microphone(self):
        mic = device(2, "muted microphone", mute=True)
        with patch.object(audio, "devices", return_value=[mic]), \
             patch.object(audio, "choose", return_value=0), \
             patch.object(audio, "list_items", return_value=[]), \
             patch.object(audio, "pactl", return_value=mic["name"]) as command:
            audio.select_device("input")
        self.assertEqual(command.call_args_list[-1], unittest.mock.call("--", "set-default-source", "muted microphone"))
        self.assertFalse(any("mute" in call.args[0] for call in command.call_args_list))

    def test_partial_move_failure_continues_other_streams(self):
        def reply(*args):
            if args[0] == "get-default-sink":
                return "speaker"
            if args[:2] == ("move-sink-input", "11"):
                raise audio.AudioError("Звуковий сервер недоступний або пристрій зник.")
            return ""
        with patch.object(audio, "devices", return_value=[device(1, "speaker")]), \
             patch.object(audio, "choose", return_value=0), \
             patch.object(audio, "list_items", return_value=[{"index": 11}, {"index": 12}]), \
             patch.object(audio, "pactl", side_effect=reply) as command, \
             patch.object(audio, "notify") as notification:
            audio.select_device("output")
        self.assertEqual(command.call_args, unittest.mock.call("move-sink-input", "12", "1"))
        notification.assert_called_once()

    def test_invalid_rofi_response_cannot_become_a_command(self):
        result = subprocess.CompletedProcess([], 0, "0; touch /tmp/injected", "")
        with patch.object(audio, "run", return_value=result) as runner:
            with self.assertRaises(audio.AudioError):
                audio.choose("Звук", ["a\nb\x00c"])
        self.assertIn("-no-custom", runner.call_args.args[0])
        self.assertIn("-config", runner.call_args.args[0])
        self.assertEqual(runner.call_args.kwargs["input_text"], "a b c\n")

    def test_rofi_escape_returns_none(self):
        result = subprocess.CompletedProcess([], 1, "", "")
        with patch.object(audio, "run", return_value=result):
            self.assertIsNone(audio.choose("Звук", ["Вихід"]))

    def test_status_graceful_and_metadata_never_reaches_polybar(self):
        with patch.object(audio, "current_device", side_effect=audio.AudioError("offline")):
            self.assertEqual(audio.status("output"), "VOL —")
            self.assertEqual(audio.status("input"), "MIC —")
        with patch.object(audio, "current_device", return_value=device(1, "%{A:danger:}", volume=42)):
            self.assertEqual(audio.status("output"), "VOL 42%")
            self.assertEqual(audio.status("input"), "MIC ON")
        with patch.object(audio, "current_device", return_value=device(1, "mic", mute=True)):
            self.assertEqual(audio.status("input"), "MIC OFF")

    def test_json_validation_and_command_error_dont_expose_stderr(self):
        with patch.object(audio, "pactl", return_value=json.dumps({"unexpected": True})):
            with self.assertRaises(audio.AudioError):
                audio.list_items("sinks")
        result = subprocess.CompletedProcess([], 1, "", "private application metadata")
        with patch.object(audio, "run", return_value=result):
            with self.assertRaises(audio.AudioError) as context:
                audio.pactl("get-default-sink")
        self.assertNotIn("private", str(context.exception))

    def test_monitor_detection_supports_pulse_sentinels(self):
        for sentinel in [None, -1, 4294967295, "4294967295", "n/a"]:
            self.assertFalse(audio.is_monitor(device(1, "mic", monitor=sentinel)))
        self.assertTrue(audio.is_monitor(device(1, "not-obvious", monitor=0)))
        self.assertTrue(audio.is_monitor(device(1, "sink.monitor")))

    def test_monitor_cannot_be_unmuted_as_microphone(self):
        with patch.object(audio, "current_device", return_value=device(1, "sink.monitor")), \
             patch.object(audio, "pactl") as command:
            with self.assertRaises(audio.AudioError):
                audio.toggle_mute("input")
        command.assert_not_called()


class AudioWatchTests(unittest.TestCase):
    def event_stream(self, payload=b""):
        reader, writer = os.pipe()
        os.write(writer, payload)
        os.close(writer)
        stream = os.fdopen(reader, "rb")
        self.addCleanup(stream.close)
        return stream

    def test_volume_event_burst_refreshes_once_without_client_event_feedback(self):
        stream = self.event_stream(
            b"Event 'new' on client #5\nEvent 'change' on sink #1\n"
            b"Event 'change' on sink #1\nEvent 'remove' on client #5\n"
        )
        refresh = MagicMock()
        audio.follow_events("output", stream, refresh)
        refresh.assert_called_once_with()

    def test_microphone_ignores_playback_events_and_tracks_source_and_default_changes(self):
        for payload, expected in ((b"Event 'change' on sink #1\n", 0),
                                  (b"Event 'change' on source #2\n", 1),
                                  (b"Event 'change' on server #4294967295\n", 1),
                                  (b"Event 'change' on card #0\n", 1)):
            with self.subTest(payload=payload):
                refresh = MagicMock()
                audio.follow_events("input", self.event_stream(payload), refresh)
                self.assertEqual(refresh.call_count, expected)

    def test_event_split_across_reads_is_not_lost(self):
        stream = self.event_stream(b"keep the descriptor readable")
        refresh = MagicMock()
        with patch.object(audio.os, "read", side_effect=[
                b"Event 'change' on si", b"nk #7\nEvent 'new' on client #8\n", b""]):
            audio.follow_events("output", stream, refresh)
        refresh.assert_called_once_with()

    def test_server_restart_reconnects_and_emits_only_changed_labels(self):
        subscribers = [MagicMock(stdout=self.event_stream()) for _ in range(2)]
        for subscriber in subscribers:
            subscriber.poll.return_value = 0
        output = io.StringIO()
        with patch.object(audio.subprocess, "Popen", side_effect=subscribers) as launch, \
                patch.object(audio, "status", side_effect=["VOL 42%", "VOL —", "VOL 43%", "VOL 43%"]), \
                patch.object(audio.time, "sleep", side_effect=[None, KeyboardInterrupt]), \
                patch.object(audio.os, "environ", {"PATH": "/usr/bin:/bin", "HOME": "/tmp/audio-check"}), \
                contextlib.redirect_stdout(output):
            audio.watch("output")
        self.assertEqual(output.getvalue().splitlines(), ["VOL 42%", "VOL —", "VOL 43%"])
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(launch.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_closed_bar_pipe_stops_the_owned_subscriber(self):
        subscriber = MagicMock(stdout=self.event_stream())
        subscriber.poll.return_value = None
        with patch.object(audio.subprocess, "Popen", return_value=subscriber), \
                patch.object(audio, "status", return_value="VOL 42%"), \
                patch("builtins.print", side_effect=BrokenPipeError), \
                patch.object(audio.time, "sleep") as pause:
            audio.watch("output")
        subscriber.terminate.assert_called_once_with()
        subscriber.wait.assert_called_once_with(timeout=2)
        pause.assert_not_called()


if __name__ == "__main__":
    unittest.main()
