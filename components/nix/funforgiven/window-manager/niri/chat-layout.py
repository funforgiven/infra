"""Arrange the two chat clients once after their startup windows appear."""

import argparse
import json
import os
import socket
import time


def chat_windows(windows):
    telegram = discord = None
    for window in sorted(windows, key=lambda window: window["id"]):
        app_id = (window.get("app_id") or "").lower()
        if app_id == "org.telegram.desktop" and window.get("title") != "Media viewer":
            telegram = telegram or window
        elif app_id == "discord" and window.get("title") != "Discord Updater":
            discord = discord or window
    return (telegram, discord) if telegram and discord else None


def wait_for_windows(timeout):
    # The event stream includes an initial snapshot, so neither launch order nor
    # connecting after the clients have opened can miss a window.
    deadline = time.monotonic() + timeout
    windows = {}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(os.environ["NIRI_SOCKET"])
        connection.sendall(b'"EventStream"\n')
        with connection.makefile("r") as events:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for Telegram and Discord")
                connection.settimeout(remaining)
                line = events.readline()
                if not line:
                    raise RuntimeError("Niri closed its event stream")
                event = json.loads(line)
                if "Err" in event:
                    raise RuntimeError(event["Err"])
                if "WindowsChanged" in event:
                    windows = {
                        window["id"]: window
                        for window in event["WindowsChanged"]["windows"]
                    }
                elif "WindowOpenedOrChanged" in event:
                    window = event["WindowOpenedOrChanged"]["window"]
                    windows[window["id"]] = window
                elif "WindowClosed" in event:
                    windows.pop(event["WindowClosed"]["id"], None)
                pair = chat_windows(windows.values())
                if pair:
                    return tuple(window["id"] for window in pair)


class Niri:
    """One IPC connection; Niri answers each JSON request line in order."""

    def __init__(self, path):
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.connect(path)
        self.stream = self.connection.makefile("rw")

    def close(self):
        self.stream.close()
        self.connection.close()

    def request(self, request):
        self.stream.write(json.dumps(request) + "\n")
        self.stream.flush()
        line = self.stream.readline()
        if not line:
            raise RuntimeError("Niri closed its IPC connection")
        reply = json.loads(line)
        if "Err" in reply:
            raise RuntimeError(reply["Err"])
        return reply["Ok"]


def arrange(request, workspace, telegram_id, discord_id):
    def query(name):
        return request(name)[name]

    def action(name, **fields):
        request({"Action": {name: fields}})

    def windows_by_id():
        return {window["id"]: window for window in query("Windows")}

    def column(window):
        position = window["layout"]["pos_in_scrolling_layout"]
        return (window["workspace_id"], position[0]) if position else None

    workspaces = query("Workspaces")
    if not any(item["name"] == workspace for item in workspaces):
        raise RuntimeError(f"The {workspace!r} workspace is missing from the Niri config")
    focused_workspace = next((item for item in workspaces if item["is_focused"]), None)
    focused_window = next((w["id"] for w in query("Windows") if w["is_focused"]), None)

    try:
        for window_id in (telegram_id, discord_id):
            action("MoveWindowToWorkspace", window_id=window_id, reference={"Name": workspace}, focus=False)
            action("MoveWindowToTiling", id=window_id)

        windows = windows_by_id()
        target_column = column(windows[telegram_id])
        members = {w["id"] for w in windows.values() if column(w) == target_column}
        if members != {telegram_id, discord_id}:
            # Isolate these clients if the command is rerun after manual layout
            # changes. Never consume an unrelated window into their column.
            for window_id in (telegram_id, discord_id):
                windows = windows_by_id()
                peers = [w for w in windows.values() if column(w) == column(windows[window_id])]
                if len(peers) > 1:
                    action("MoveWindowToFloating", id=window_id)
                    action("MoveWindowToTiling", id=window_id)
            action("FocusWindow", id=telegram_id)
            action("MoveColumnToFirst")
            action("FocusWindow", id=discord_id)
            action("MoveColumnToIndex", index=2)
            action("FocusWindow", id=telegram_id)
            action("ConsumeWindowIntoColumn")

        action("FocusWindow", id=telegram_id)
        if windows_by_id()[telegram_id]["layout"]["pos_in_scrolling_layout"][1] != 1:
            action("MoveWindowUp")
        action("SetColumnDisplay", display="Normal")
        action("SetColumnWidth", change={"SetProportion": 100.0})
        # Automatic heights divide the available area evenly, including gaps
        # and panel reservations, without hard-coding monitor dimensions.
        action("ResetWindowHeight", id=telegram_id)
        action("ResetWindowHeight", id=discord_id)
    finally:
        if focused_window is not None and focused_window in windows_by_id():
            action("FocusWindow", id=focused_window)
        elif focused_workspace:
            action("FocusMonitor", output=focused_workspace["output"])
            name = focused_workspace["name"]
            action("FocusWorkspace", reference={"Name": name} if name else {"Index": focused_workspace["idx"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="chat")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    pair = wait_for_windows(args.timeout)
    niri = Niri(os.environ["NIRI_SOCKET"])
    try:
        arrange(niri.request, args.workspace, *pair)
    finally:
        niri.close()


if __name__ == "__main__":
    main()
