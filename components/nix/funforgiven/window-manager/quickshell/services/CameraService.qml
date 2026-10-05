pragma Singleton

import QtQuick
import Quickshell.Io
import ".." as Shell

QtObject {
    id: root

    property var state: ({
            connected: false,
            awake: false,
            controls: {},
            presets: []
        })
    property string error: ""
    property bool watching: false
    property int pendingId: 0
    property int nextId: 1
    property var queue: []
    readonly property bool busy: pendingId !== 0
    readonly property bool awake: state.connected === true && state.awake === true
    readonly property bool privateAudio: state.connected === true && state.voiceMask === 0 && state.microphoneEnabled === false

    function request(action, parameters) {
        var command = Object.assign({}, parameters || {}, {
            action: action,
            id: nextId++
        });
        // Slider updates coalesce while the helper is busy; discrete actions
        // retain their order. No command string is evaluated by a shell.
        var next = queue.slice();
        if (action === "set") {
            next = next.filter(function (item) {
                return item.action !== "set" || item.control !== command.control;
            });
        }
        next.push(command);
        queue = next;
        flush();
    }

    function flush() {
        if (pendingId !== 0 || !helper.running || queue.length === 0)
            return;
        var command = queue[0];
        queue = queue.slice(1);
        pendingId = command.id;
        helper.write(JSON.stringify(command) + "\n");
        timeout.restart();
    }

    function receive(line) {
        try {
            var message = JSON.parse(line);
            if (message.state !== undefined)
                state = message.state;
            if (message.id !== null && message.id === pendingId) {
                error = message.ok === true ? "" : String(message.error || "Camera action failed");
                pendingId = 0;
                timeout.stop();
                flush();
            }
        } catch (failure) {
            error = "Invalid camera helper response: " + String(failure);
        }
    }

    onWatchingChanged: request("watch", {
        value: watching
    })

    property Process helper: Process {
        command: [Shell.ShellConfig.cameraController, "serve"]
        running: true
        stdinEnabled: true
        stdout: SplitParser {
            onRead: line => root.receive(line)
        }
        stderr: SplitParser {
            onRead: line => console.warn("Camera helper: " + line)
        }
        onStarted: root.request("watch", {
            value: root.watching
        })
        onExited: function (exitCode) { // qmllint disable signal-handler-parameters
            root.state = {
                connected: false,
                awake: false,
                controls: {},
                presets: []
            };
            root.pendingId = 0;
            root.queue = [];
            root.error = "Camera helper stopped";
            root.timeout.stop();
        }
    }

    property Timer restart: Timer {
        interval: 2000
        running: !root.helper.running
        onTriggered: root.helper.running = true
    }

    property Timer timeout: Timer {
        interval: 25000
        onTriggered: {
            root.error = "Camera did not answer in time";
            root.helper.running = false;
        }
    }
}
