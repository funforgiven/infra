pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Scope {
    id: root

    readonly property bool active: policy.active

    PresencePolicy {
        id: policy
    }

    IpcHandler {
        target: "amoled"

        function activate(): void {
            policy.idle();
        }

        function deactivate(): void {
            policy.input();
        }

        function updatePresence(state: string): void {
            policy.presence(state);
        }

        function status(): string {
            return JSON.stringify({
                presence: policy.presenceState,
                inputIdle: policy.inputIdle,
                inputOverride: policy.wakeGrace.running,
                active: root.active
            });
        }

        function isVisible(): bool {
            return root.active;
        }
    }

    Variants {
        model: Quickshell.screens

        PanelWindow { // qmllint disable uncreatable-type
            required property var modelData

            screen: modelData
            visible: root.active
            color: "#000000"
            exclusionMode: ExclusionMode.Ignore
            mask: Region {}

            anchors {
                top: true
                right: true
                bottom: true
                left: true
            }

            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "funforgiven-amoled"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        }
    }
}
