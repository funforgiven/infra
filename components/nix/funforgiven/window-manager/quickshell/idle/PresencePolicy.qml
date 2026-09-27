import QtQuick

QtObject {
    id: root

    property bool inputIdle: false
    property string presenceState: "unknown"
    readonly property bool active: presenceState === "on" ? false : presenceState === "off" ? !wakeGrace.running : inputIdle

    // A crashed reader or a broken HA connection must not leave a stale
    // occupied state keeping the display awake indefinitely.
    property Timer presenceLease: Timer {
        interval: 45000
        onTriggered: root.presenceState = "unknown"
    }

    // Input can wake the display while the sensor is still reporting clear.
    property Timer wakeGrace: Timer {
        interval: 30000
    }

    function idle(): void {
        inputIdle = true;
    }

    function input(): void {
        if (active || wakeGrace.running)
            wakeGrace.restart();
        inputIdle = false;
    }

    function presence(state: string): void {
        presenceState = state === "on" || state === "off" ? state : "unknown";
        if (presenceState === "on")
            wakeGrace.stop();
        presenceLease.restart();
    }
}
