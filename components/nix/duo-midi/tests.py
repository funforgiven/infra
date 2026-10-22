"""Exercise pad dispatch, focused-app selection and safe webhook calls without hardware."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.error


sys.path.insert(0, sys.argv.pop(1))
import audio  # noqa: E402
import home  # noqa: E402
import pads  # noqa: E402


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
        self.focus = audio.focus_from_windows([
            {"id": 1, "app_id": "hayase", "pid": 10, "is_focused": True},
            {"id": 2, "app_id": "other", "pid": 20, "is_focused": False},
        ], self.read_process)

    def select(self, graph):
        return audio.matching_streams(graph, self.focus, self.read_process)

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
            audio.focus_from_windows([{"id": 1, "title": "hayase", "is_focused": True}], lambda _: None)
        with self.assertRaises(ValueError):
            audio.focus_from_windows([], self.read_process)

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
        focus = audio.Focus(1, "hayase", None, None, frozenset())
        run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(graph), ""))
        with patch.object(audio.subprocess, "run", run), patch.object(audio, "notify"):
            result = audio.route(focus, "game")
        self.assertEqual(result["moved"], 1)
        self.assertEqual(run.call_args_list[1].args[0], [
            "funforgiven-audioctl", "move-stream", "3", "1003", "game",
        ])

    def test_dry_run_and_no_audio_never_move_a_stream(self):
        focus = audio.Focus(1, "hayase", None, None, frozenset())
        graph = [node(3, **{"application.id": "hayase"})]
        run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(graph), ""))
        with patch.object(audio.subprocess, "run", run):
            self.assertEqual(audio.route(focus, "music", dry_run=True)["streams"], [{"id": 3, "serial": 1003}])
        self.assertEqual(run.call_count, 1)
        run.return_value.stdout = "[]"
        with patch.object(audio.subprocess, "run", run), self.assertRaisesRegex(ValueError, "start audio first"):
            audio.route(focus, "music")
        self.assertEqual(run.call_count, 2)


class PadTests(unittest.TestCase):
    def test_each_pad_reaches_only_its_owner(self):
        self.assertFalse(set(audio.Dispatcher.controls) & set(home.Dispatcher.controls))
        groups = [Mock(controls=audio.Dispatcher.controls), Mock(controls=home.Dispatcher.controls)]
        receive = pads.receiver(groups)
        for control in range(102, 108):
            receive(message(control=control))
        for event in [message(value=0), message(channel=0), message(control=27),
                      message(control=101), message(control=108), message(kind="note_on")]:
            receive(event)
        self.assertEqual([c.args[0] for c in groups[0].receive.call_args_list], [102, 103, 104, 105])
        self.assertEqual([c.args[0] for c in groups[1].receive.call_args_list], [106, 107])

    def test_port_reconnect_uses_name_and_rejects_other_devices_or_ambiguity(self):
        for number in [16, 24]:
            name = f"RODECaster Duo:RODECaster Duo MIDI 1 {number}:0"
            self.assertEqual(pads.select_port(["Midi Through:Midi Through Port-0 14:0", name]), name)
        self.assertEqual(pads.select_port(["RØDECaster Duo:RØDECaster Duo MIDI 1 24:0"]),
                         "RØDECaster Duo:RØDECaster Duo MIDI 1 24:0")
        self.assertIsNone(pads.select_port(["Other:RODECaster Duo MIDI 1 16:0", "Other MIDI"]))
        self.assertIsNone(pads.select_port([
            "RODECaster Duo:RODECaster Duo MIDI 1 16:0", "RODECaster Duo:RODECaster Duo MIDI 1 24:0",
        ]))

    def test_bad_webhook_credential_keeps_audio_routing(self):
        with patch.object(home, "load_webhooks", side_effect=ValueError("bad")), \
                self.assertLogs("duo-midi", "ERROR"):
            groups = pads.dispatchers(threading.Event())
        self.assertEqual([type(g) for g in groups], [audio.Dispatcher])


class AudioPadTests(unittest.TestCase):
    def test_unrelated_controls_are_ignored(self):
        dispatcher = audio.Dispatcher(threading.Event(), capture=Mock(), report=Mock())
        for control in [27, 106, 107]:
            dispatcher.receive(control)
        dispatcher.capture.assert_not_called()
        self.assertTrue(dispatcher.events.empty())

    def test_press_captures_focus_before_worker_runs_and_ignores_duplicates(self):
        first = audio.Focus(1, "first", None, None, frozenset())
        second = audio.Focus(2, "second", None, None, frozenset())
        capture = Mock(side_effect=[first, second])
        dispatcher = audio.Dispatcher(threading.Event(), capture=capture, report=Mock())
        with patch.object(audio.time, "monotonic", side_effect=[1, 1.01, 2]):
            dispatcher.receive(102)
            dispatcher.receive(102)
            dispatcher.receive(105)
        self.assertEqual(dispatcher.events.get_nowait()[:2], (first, "system"))
        self.assertEqual(dispatcher.events.get_nowait()[:2], (second, "music"))
        self.assertTrue(dispatcher.events.empty())
        self.assertEqual(capture.call_count, 2)


class HomePadTests(unittest.TestCase):
    def test_only_home_pads_trigger(self):
        dispatcher = home.Dispatcher(threading.Event(), Mock(), lambda: 10)
        for cc in [0, 17, 27, 35, 102, 103, 104, 105]:
            dispatcher.receive(cc)
        self.assertTrue(dispatcher.events.empty())

    def test_duplicates_are_suppressed_independently(self):
        clock = Mock(side_effect=[10, 10.01, 10.1, 10.5, 12.2])
        dispatcher = home.Dispatcher(threading.Event(), Mock(), clock)
        for cc in [106, 106, 107, 107, 107]:
            dispatcher.receive(cc)
        self.assertEqual([dispatcher.events.get_nowait()[0] for _ in range(3)],
                         ["loft-light", "loft-airflow", "loft-airflow"])
        self.assertTrue(dispatcher.events.empty())

    def test_stale_requests_are_never_replayed_after_an_outage(self):
        send = Mock()
        dispatcher = home.Dispatcher(threading.Event(), send, lambda: 10)
        dispatcher.dispatch("loft-light", 6)
        send.assert_not_called()
        dispatcher.dispatch("loft-light", 9)
        send.assert_called_once_with("loft-light")

    def test_http_posts_once_without_payload_or_redirects(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        result = home.trigger("loft-light", {"loft-light": "https://example.test/capability"}, opener=opener)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.data, b"")
        self.assertTrue(result["submitted"])
        opener.open.assert_called_once()
        self.assertIsNone(home.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.test"))

    def test_timeout_does_not_retry_or_disclose_secret_url(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("secret-webhook-value")
        with self.assertRaises(ValueError) as caught:
            home.trigger("loft-airflow", {"loft-airflow": "https://example.test/secret-webhook-value"}, opener=opener)
        self.assertNotIn("secret-webhook-value", str(caught.exception))
        opener.open.assert_called_once()

    def test_dry_run_makes_no_request(self):
        opener = Mock()
        self.assertEqual(home.trigger("loft-light", {}, True, opener), {"action": "loft-light", "send": False})
        opener.open.assert_not_called()

    def test_credential_validation_rejects_plaintext_other_hosts_and_extra_actions(self):
        url = "https://home.fahrican.com/api/webhook/" + "x" * 43
        valid = {"loft-light": url, "loft-airflow": url}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": directory}):
            path = Path(directory, "ha-webhooks")
            path.write_text(json.dumps(valid))
            self.assertEqual(home.load_webhooks(), valid)
            for bad in [valid | {"loft-light": url.replace("https:", "http:")},
                        valid | {"loft-light": url.replace("home.fahrican.com", "other.test")},
                        valid | {"loft-light": url + "?extra=1"},
                        valid | {"arbitrary-action": url}]:
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    home.load_webhooks()


unittest.main()
