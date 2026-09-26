"""Exercise focused-app selection and MIDI dispatch without desktop hardware."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


source = Path(sys.argv.pop(1))
spec = importlib.util.spec_from_file_location("midi_router", source)
router = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = router
spec.loader.exec_module(router)


def node(number, **props):
    return {"id": number, "type": "PipeWire:Interface:Node", "info": {"props": {
        "media.class": "Stream/Output/Audio", "object.serial": number + 1000, **props,
    }}}


def message(control=102, channel=15, value=127, kind="control_change"):
    return SimpleNamespace(type=kind, channel=channel, control=control, value=value)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.processes = {10: (1, 100), 11: (10, 110), 20: (1, 200), 21: (20, 210)}
        self.read_process = self.processes.get
        self.focus = router.focus_from_windows([
            {"id": 1, "app_id": "hayase", "pid": 10, "is_focused": True},
            {"id": 2, "app_id": "other", "pid": 20, "is_focused": False},
        ], self.read_process)

    def select(self, graph):
        return router.matching_streams(graph, self.focus, self.read_process)

    def test_alsa_child_identity_on_client_and_multiple_streams(self):
        graph = [
            {"id": 90, "type": "PipeWire:Interface:Client", "info": {"props": {
                "application.process.id": 11,
                "application.name": "PipeWire ALSA [hayase]",
            }}},
            node(1, **{"client.id": 90}), node(2, **{"client.id": 90}),
            node(3, **{"application.process.id": 21}),
        ]
        self.assertEqual(self.select(graph), [{"id": 1, "serial": 1001}, {"id": 2, "serial": 1002}])

    def test_desktop_id_and_binary_match_exactly(self):
        graph = [node(1, **{"application.id": "HAYASE.desktop"}),
                 node(2, **{"application.process.binary": "hayase"}),
                 node(3, **{"application.id": "hayase-other"}),
                 node(4, **{"application.name": "hayase"})]
        self.assertEqual([n["id"] for n in self.select(graph)], [1, 2])

    def test_no_window_titles_or_unnamed_app_fallback(self):
        with self.assertRaises(ValueError):
            router.focus_from_windows([{"id": 1, "title": "hayase", "is_focused": True}], lambda _: None)
        with self.assertRaises(ValueError):
            router.focus_from_windows([], self.read_process)

    def test_capture_hardware_internal_and_marked_nodes_are_excluded(self):
        graph = [node(1, **{"application.process.id": 11, "media.class": "Stream/Input/Audio"}),
                 node(2, **{"application.process.id": 11, "funforgiven.audio.kind": "bridge"}),
                 node(3, **{"application.process.id": 11, "media.class": "Stream/Output/Audio/Internal"}),
                 node(4, **{"application.process.id": 11, "stream.monitor": True}),
                 node(5, **{"application.process.id": 11, "media.class": "Audio/Sink"})]
        self.assertEqual(self.select(graph), [])

    def test_reused_focused_pid_is_rejected(self):
        self.processes[10] = (1, 999)
        with self.assertRaisesRegex(ValueError, "exited"):
            self.select([node(1, **{"application.id": "hayase"})])

    def test_a_different_window_blocks_process_ancestry(self):
        # The other app was launched from the focused terminal. Its audio must
        # not be treated as terminal audio just because the terminal is an ancestor.
        self.processes[20] = (10, 200)
        self.assertEqual(self.select([node(1, **{"application.process.id": 21})]), [])

    def test_host_pid_can_match_when_namespace_pid_does_not(self):
        self.assertEqual(self.select([node(1, **{
            "application.process.id": 2, "pipewire.sec.pid": 11,
        })]), [{"id": 1, "serial": 1001}])

    def test_process_cycles_terminate(self):
        self.processes[30] = (31, 300)
        self.processes[31] = (30, 310)
        self.assertEqual(self.select([node(1, **{"application.process.id": 30})]), [])

    def test_route_uses_existing_helper_with_ids_and_serials(self):
        graph = [node(3, **{"application.id": "hayase"})]
        focus = router.Focus(1, "hayase", None, None, frozenset())
        run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(graph), ""))
        with patch.object(router.subprocess, "run", run), patch.object(router, "notify"):
            result = router.route(focus, "game")
        self.assertEqual(result["moved"], 1)
        self.assertEqual(run.call_args_list[1].args[0], [
            "funforgiven-audioctl", "move-stream", "3", "1003", "game",
        ])

    def test_dry_run_and_no_audio_never_move_a_stream(self):
        focus = router.Focus(1, "hayase", None, None, frozenset())
        graph = [node(3, **{"application.id": "hayase"})]
        run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(graph), ""))
        with patch.object(router.subprocess, "run", run):
            self.assertEqual(router.route(focus, "music", dry_run=True)["streams"], [{"id": 3, "serial": 1003}])
        self.assertEqual(run.call_count, 1)
        run.return_value.stdout = "[]"
        with patch.object(router.subprocess, "run", run), self.assertRaisesRegex(ValueError, "start audio first"):
            router.route(focus, "music")
        self.assertEqual(run.call_count, 2)


class MidiTests(unittest.TestCase):
    def test_four_buttons_and_unrelated_controls(self):
        self.assertEqual([router.midi_target(message(control=n)) for n in range(102, 106)],
                         ["system", "game", "voice", "music"])
        for event in [message(value=0), message(channel=0), message(control=27), message(kind="note_on")]:
            self.assertIsNone(router.midi_target(event))

    def test_port_reconnect_uses_name_and_rejects_other_devices_or_ambiguity(self):
        for number in [16, 24]:
            name = f"RODECaster Duo:RODECaster Duo MIDI 1 {number}:0"
            self.assertEqual(router.select_port(["Midi Through:Midi Through Port-0 14:0", name]), name)
        self.assertIsNone(router.select_port(["Other:RODECaster Duo MIDI 1 16:0"]))
        self.assertIsNone(router.select_port([
            "RODECaster Duo:RODECaster Duo MIDI 1 16:0", "RODECaster Duo:RODECaster Duo MIDI 1 24:0",
        ]))

    def test_press_captures_focus_before_worker_runs_and_ignores_duplicates(self):
        first = router.Focus(1, "first", None, None, frozenset())
        second = router.Focus(2, "second", None, None, frozenset())
        capture = Mock(side_effect=[first, second])
        dispatcher = router.Dispatcher(threading.Event(), capture=capture, report=Mock())
        with patch.object(router.time, "monotonic", side_effect=[1, 1.01, 2]):
            dispatcher.receive(message())
            dispatcher.receive(message())
            dispatcher.receive(message(control=105))
        self.assertEqual(dispatcher.events.get_nowait()[:2], (first, "system"))
        self.assertEqual(dispatcher.events.get_nowait()[:2], (second, "music"))
        self.assertTrue(dispatcher.events.empty())
        self.assertEqual(capture.call_count, 2)


unittest.main()
