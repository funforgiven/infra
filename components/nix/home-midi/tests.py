"""Check pad isolation, deduplication and safe HTTP dispatch without hardware."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.error


spec = importlib.util.spec_from_file_location("controls", sys.argv.pop(1))
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


def message(control=106, channel=15, value=127, kind="control_change"):
    return SimpleNamespace(type=kind, channel=channel, control=control, value=value)


class ControlsTests(unittest.TestCase):
    def test_only_home_pads_trigger(self):
        self.assertEqual(controls.midi_action(message()), "loft-light")
        self.assertEqual(controls.midi_action(message(control=107)), "loft-airflow")
        for event in [message(control=cc) for cc in [0, 17, 27, 35, 102, 103, 104, 105]] + [
            message(channel=0), message(value=0), message(kind="note_on")
        ]:
            self.assertIsNone(controls.midi_action(event))

    def test_duplicates_are_suppressed_independently(self):
        clock = Mock(side_effect=[10, 10.01, 10.1, 10.5, 12.2])
        dispatcher = controls.Dispatcher(threading.Event(), Mock(), clock)
        for cc in [106, 106, 107, 107, 107]:
            dispatcher.receive(message(control=cc))
        self.assertEqual([dispatcher.events.get_nowait()[0] for _ in range(3)],
                         ["loft-light", "loft-airflow", "loft-airflow"])
        self.assertTrue(dispatcher.events.empty())

    def test_stale_requests_are_never_replayed_after_an_outage(self):
        send = Mock()
        dispatcher = controls.Dispatcher(threading.Event(), send, lambda: 10)
        dispatcher.dispatch("loft-light", 6)
        send.assert_not_called()
        dispatcher.dispatch("loft-light", 9)
        send.assert_called_once_with("loft-light")

    def test_only_the_unique_duo_is_opened(self):
        name = "RODECaster Duo:RODECaster Duo MIDI 1 24:0"
        self.assertEqual(controls.select_port([name, "Other MIDI"]), name)
        self.assertIsNone(controls.select_port([name, name.replace("24", "16")]))
        self.assertIsNone(controls.select_port(["Other:RODECaster Duo MIDI 1 24:0"]))

    def test_http_posts_once_without_payload_or_redirects(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        result = controls.trigger("loft-light", {"loft-light": "https://example.test/capability"}, opener=opener)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.data, b"")
        self.assertTrue(result["submitted"])
        opener.open.assert_called_once()
        self.assertIsNone(controls.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.test"))

    def test_timeout_does_not_retry_or_disclose_secret_url(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("secret-webhook-value")
        with self.assertRaises(ValueError) as caught:
            controls.trigger("loft-airflow", {"loft-airflow": "https://example.test/secret-webhook-value"}, opener=opener)
        self.assertNotIn("secret-webhook-value", str(caught.exception))
        opener.open.assert_called_once()

    def test_dry_run_makes_no_request(self):
        opener = Mock()
        self.assertEqual(controls.trigger("loft-light", {}, True, opener), {"action": "loft-light", "send": False})
        opener.open.assert_not_called()

    def test_credential_validation_rejects_plaintext_other_hosts_and_extra_actions(self):
        url = "https://home.fahrican.com/api/webhook/" + "x" * 43
        valid = {"loft-light": url, "loft-airflow": url}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": directory}):
            path = Path(directory, "ha-webhooks")
            path.write_text(json.dumps(valid))
            self.assertEqual(controls.load_webhooks(), valid)
            for bad in [valid | {"loft-light": url.replace("https:", "http:")},
                        valid | {"loft-light": url.replace("home.fahrican.com", "other.test")},
                        valid | {"loft-light": url + "?extra=1"},
                        valid | {"arbitrary-action": url}]:
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    controls.load_webhooks()


unittest.main()
