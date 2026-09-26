import QtQuick
import Quickshell
import ".." as Shell
import "../components" as Components
import "../services" as Services

Components.IconButton {
    id: root

    activeFocusOnTab: false

    signal requested

    readonly property bool warning: !Services.AudioService.ready || Services.AudioService.defaultWarning || Services.AudioActions.recentErrors.length > 0

    iconSource: Quickshell.iconPath("audio-card-symbolic", "audio-volume-high")
    accessibleName: warning ? "Audio mixer, needs attention" : "Audio mixer"
    tooltipText: {
        if (!Services.AudioService.ready)
            return "Audio connecting";
        if (Services.AudioService.defaultWarning)
            return "Output mismatch";
        if (Services.AudioActions.recentErrors.length > 0)
            return "Audio error";
        return "Audio routing · RØDECaster Duo";
    }
    accent: Shell.Theme.systemAccent
    attention: warning
    onClicked: button => {
        if (button === Qt.LeftButton)
            root.requested();
    }
}
