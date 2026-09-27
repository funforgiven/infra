"""Arrange the two chat clients once after their startup windows appear."""

import argparse
import json
import os
import socket
import subprocess
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


def arrange(niri, workspace, telegram_id, discord_id):
    def query(command):
        return json.loads(subprocess.check_output([niri, "msg", "--json", command]))

    def action(*arguments):
        subprocess.run([niri, "msg", "action", *map(str, arguments)], check=True)

    def windows_by_id():
        return {window["id"]: window for window in query("windows")}

    def column(window):
        position = window["layout"]["pos_in_scrolling_layout"]
        return (window["workspace_id"], position[0]) if position else None

    workspaces = query("workspaces")
    if not any(item["name"] == workspace for item in workspaces):
        raise RuntimeError(f"The {workspace!r} workspace is missing from the Niri config")
    focused_workspace = next((item for item in workspaces if item["is_focused"]), None)
    focused_window = next((w["id"] for w in query("windows") if w["is_focused"]), None)

    try:
        for window_id in (telegram_id, discord_id):
            action("move-window-to-workspace", "--window-id", window_id, "--focus", "false", workspace)
            action("move-window-to-tiling", "--id", window_id)

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
                    action("move-window-to-floating", "--id", window_id)
                    action("move-window-to-tiling", "--id", window_id)
            action("focus-window", "--id", telegram_id)
            action("move-column-to-first")
            action("focus-window", "--id", discord_id)
            action("move-column-to-index", 2)
            action("focus-window", "--id", telegram_id)
            action("consume-window-into-column")

        action("focus-window", "--id", telegram_id)
        if windows_by_id()[telegram_id]["layout"]["pos_in_scrolling_layout"][1] != 1:
            action("move-window-up")
        action("set-column-display", "normal")
        action("set-column-width", "100%")
        # Automatic heights divide the available area evenly, including gaps
        # and panel reservations, without hard-coding monitor dimensions.
        action("reset-window-height", "--id", telegram_id)
        action("reset-window-height", "--id", discord_id)
    finally:
        if focused_window is not None and focused_window in windows_by_id():
            action("focus-window", "--id", focused_window)
        elif focused_workspace:
            action("focus-monitor", focused_workspace["output"])
            action("focus-workspace", focused_workspace["name"] or focused_workspace["idx"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--niri", default="niri")
    parser.add_argument("--workspace", default="chat")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    arrange(args.niri, args.workspace, *wait_for_windows(args.timeout))


if __name__ == "__main__":
    main()
