pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import ".." as Shell
import "../components" as Components

Item {
    id: root

    property string text: ""
    property string icon: ""
    property string tooltipText: ""
    property bool checked: false
    signal toggled

    implicitHeight: Shell.Theme.controlSize
    implicitWidth: content.implicitWidth
    activeFocusOnTab: enabled
    opacity: enabled ? 1 : Shell.Theme.disabledOpacity
    Accessible.role: Accessible.CheckBox
    Accessible.name: text
    Accessible.checkable: true
    Accessible.checked: checked
    Accessible.onToggleAction: if (root.enabled)
        root.toggled()
    Keys.onSpacePressed: if (root.enabled)
        root.toggled()
    Keys.onReturnPressed: if (root.enabled)
        root.toggled()

    RowLayout {
        id: content
        anchors.fill: parent
        spacing: Shell.Theme.spacingSmall
        Components.SemanticIcon {
            visible: root.icon.length > 0
            source: root.icon.length > 0 ? Qt.resolvedUrl("icons/" + root.icon + ".svg") : ""
            Layout.preferredWidth: Shell.Theme.iconSmallSize
            Layout.preferredHeight: Shell.Theme.iconSmallSize
            checked: root.checked
        }
        Text {
            Layout.fillWidth: true
            text: root.text
            color: Shell.Theme.primaryText
            font.family: Shell.Theme.sansFont
            font.pixelSize: Shell.Theme.labelFontSize
        }
        Rectangle {
            Layout.preferredWidth: 38
            Layout.preferredHeight: 22
            radius: Shell.Theme.radiusPill
            color: root.checked ? Shell.Theme.systemAccent : Shell.Theme.outlineStrong
            Rectangle {
                x: root.checked ? parent.width - width - 3 : 3
                y: 3
                width: 16
                height: 16
                radius: 8
                color: root.checked ? Shell.Theme.accentText : Shell.Theme.primaryText
                Behavior on x {
                    NumberAnimation {
                        duration: Shell.Theme.animationFast
                    }
                }
            }
        }
    }
    Components.FocusRing {
        active: root.activeFocus
        ringRadius: Shell.Theme.radiusSmall
    }
    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled()
    }
    Components.Tooltip {
        visible: pointer.containsMouse && root.tooltipText.length > 0
        text: root.tooltipText
    }
}
