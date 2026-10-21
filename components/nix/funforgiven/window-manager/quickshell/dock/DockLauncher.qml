import QtQuick
import Quickshell
import ".." as Shell
import "../components" as Components
import "../launcher" as Launcher

Item {
    id: root

    readonly property bool hovered: pointer.containsMouse
    readonly property bool pressed: pointer.pressed

    implicitWidth: 56
    implicitHeight: 56

    Accessible.name: "Applications"
    Accessible.description: Launcher.Launcher.opened ? "Launcher open" : "Launcher closed"
    Accessible.role: Accessible.Button
    Accessible.onPressAction: Launcher.Launcher.toggle()

    Item {
        id: visual

        anchors.fill: parent
        anchors.margins: 1
        scale: root.pressed ? Shell.Theme.pressedScale : 1
        transformOrigin: Item.Center

        Behavior on scale {
            NumberAnimation {
                duration: Shell.Theme.animationFast
                easing.type: Shell.Theme.easingStandard
            }
        }

        Components.Surface {
            anchors.fill: parent
            interactive: true
            hovered: root.hovered
            pressed: root.pressed
            selected: Launcher.Launcher.opened
            surfaceColor: "transparent"
            outlineColor: "transparent"
            outlineWidth: Launcher.Launcher.opened ? Shell.Theme.outlineWidth : 0
        }

        Components.SemanticIcon {
            anchors.centerIn: parent
            width: 32
            height: 32
            source: Quickshell.iconPath("view-app-grid-symbolic", "system-search-symbolic")
            hovered: root.hovered
            pressed: root.pressed
            active: Launcher.Launcher.opened
        }

        Rectangle {
            visible: Launcher.Launcher.opened
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 3
            width: 22
            height: 3
            radius: Shell.Theme.radiusPill
            color: Shell.Theme.systemAccent
        }
    }

    MouseArea {
        id: pointer

        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.PointingHandCursor
        onClicked: Launcher.Launcher.toggle()
    }

    Components.Tooltip {
        visible: pointer.containsMouse
        text: "Applications"
    }
}
