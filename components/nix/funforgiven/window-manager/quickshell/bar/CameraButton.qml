import QtQuick
import "../components" as Components
import "../services" as Services

Components.IconButton {
    signal requested

    activeFocusOnTab: false
    iconSource: Qt.resolvedUrl("../camera/icons/webcam.svg")
    accessibleName: "OBSBOT camera controls"
    checked: Services.CameraService.state.awake === true
    attention: Services.CameraService.error.length > 0
    tooltipText: Services.CameraService.state.connected === true ? (Services.CameraService.state.awake === true ? "OBSBOT Tiny 3 · Awake" : "OBSBOT Tiny 3 · Sleeping") : "OBSBOT Tiny 3 · Disconnected"
    onClicked: button => {
        if (button === Qt.LeftButton)
            requested();
    }
}
