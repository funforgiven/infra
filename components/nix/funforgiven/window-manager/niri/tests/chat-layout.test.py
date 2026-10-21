import importlib.util
import io
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("chat_layout", sys.argv.pop(1))
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


def window(window_id, app_id, title="Main window"):
    return {"id": window_id, "app_id": app_id, "title": title}


TELEGRAM = window(4, "org.telegram.desktop")
DISCORD = window(3, "discord")
VIEWER = window(1, "org.telegram.desktop", "Media viewer")
UPDATER = window(2, "discord", "Discord Updater")


class StartupWindowsTest(unittest.TestCase):
    def wait(self, events, timeout=120):
        connection = MagicMock()
        connection.makefile.return_value = io.StringIO(
            "".join(json.dumps(event) + "\n" for event in events)
        )
        with (
            patch.dict(layout.os.environ, {"NIRI_SOCKET": "/test/niri.sock"}),
            patch.object(layout.socket, "socket") as constructor,
        ):
            constructor.return_value.__enter__.return_value = connection
            return layout.wait_for_windows(timeout)

    def test_clients_already_open_with_auxiliary_windows(self):
        self.assertEqual(
            self.wait([{"WindowsChanged": {"windows": [VIEWER, UPDATER, DISCORD, TELEGRAM]}}]),
            (4, 3),
        )

    def test_either_launch_order_and_unrelated_events(self):
        for first, second in ((TELEGRAM, DISCORD), (DISCORD, TELEGRAM)):
            with self.subTest(first=first["app_id"]):
                self.assertEqual(
                    self.wait([
                        {"Ok": "Handled"},
                        {"WindowsChanged": {"windows": [VIEWER, UPDATER]}},
                        {"WindowOpenedOrChanged": {"window": first}},
                        {"WindowFocusChanged": {"id": first["id"]}},
                        {"WindowOpenedOrChanged": {"window": second}},
                    ]),
                    (4, 3),
                )

    def test_closed_window_is_not_used(self):
        replacement = dict(TELEGRAM, id=9)
        self.assertEqual(
            self.wait([
                {"WindowsChanged": {"windows": [TELEGRAM]}},
                {"WindowClosed": {"id": TELEGRAM["id"]}},
                {"WindowOpenedOrChanged": {"window": DISCORD}},
                {"WindowOpenedOrChanged": {"window": replacement}},
            ]),
            (9, 3),
        )

    def test_missing_client_fails_without_arranging_other_windows(self):
        with self.assertRaisesRegex(RuntimeError, "closed its event stream"):
            self.wait([{"WindowsChanged": {"windows": [TELEGRAM, UPDATER]}}])
        with self.assertRaises(TimeoutError):
            self.wait([], timeout=0)


def placed(window_id, column, row, focused=False):
    return {"id": window_id, "workspace_id": 7, "is_focused": focused,
            "layout": {"pos_in_scrolling_layout": [column, row]}}


class ArrangeTest(unittest.TestCase):
    def test_arranges_through_one_connection_and_restores_focus(self):
        windows = [placed(4, 1, 2), placed(3, 1, 1), placed(8, 2, 1, focused=True)]
        sent = []

        def request(message):
            sent.append(message)
            if message == "Workspaces":
                return {"Workspaces": [{"name": "chat", "is_focused": True, "output": "DP-1", "idx": 2}]}
            if message == "Windows":
                return {"Windows": windows}
            return "Handled"

        layout.arrange(request, "chat", 4, 3)
        actions = [next(iter(m["Action"].items())) for m in sent if isinstance(m, dict)]
        self.assertEqual(actions, [
            ("MoveWindowToWorkspace", {"window_id": 4, "reference": {"Name": "chat"}, "focus": False}),
            ("MoveWindowToTiling", {"id": 4}),
            ("MoveWindowToWorkspace", {"window_id": 3, "reference": {"Name": "chat"}, "focus": False}),
            ("MoveWindowToTiling", {"id": 3}),
            ("FocusWindow", {"id": 4}),
            ("MoveWindowUp", {}),
            ("SetColumnDisplay", {"display": "Normal"}),
            ("SetColumnWidth", {"change": {"SetProportion": 100.0}}),
            ("ResetWindowHeight", {"id": 4}),
            ("ResetWindowHeight", {"id": 3}),
            ("FocusWindow", {"id": 8}),
        ])

    def test_missing_workspace_and_errors_are_reported(self):
        with self.assertRaisesRegex(RuntimeError, "missing"):
            layout.arrange(lambda _: {"Workspaces": []}, "chat", 4, 3)
        niri = layout.Niri.__new__(layout.Niri)
        niri.stream = io.StringIO('{"Err":"No such window"}\n')
        niri.stream.flush = lambda: None
        with patch.object(niri.stream, "write"):
            with self.assertRaisesRegex(RuntimeError, "No such window"):
                niri.request({"Action": {"FocusWindow": {"id": 1}}})


if __name__ == "__main__":
    unittest.main()
