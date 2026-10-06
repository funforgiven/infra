pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import ".." as Shell
import "../components" as Components

Item {
    id: root

    property string text: ""
    property string icon: ""
    property string tooltipText: text
    property string subtitle: ""
    property bool checked: false
    property bool filled: false
    readonly property bool hovered: pointer.containsMouse
    readonly property bool pressed: pointer.pressed || keyboardPressed
    property bool keyboardPressed: false

    signal clicked

    implicitWidth: content.implicitWidth + Shell.Theme.spacingLarge * 2
    implicitHeight: subtitle.length > 0 ? 66 : Shell.Theme.controlSize
    activeFocusOnTab: enabled
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: if (root.enabled)
        root.clicked()
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            root.keyboardPressed = true;
            event.accepted = true;
        }
    }
    Keys.onReleased: event => {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            if (root.keyboardPressed && root.enabled)
                root.clicked();
            root.keyboardPressed = false;
            event.accepted = true;
        }
    }
    onActiveFocusChanged: if (!activeFocus)
        keyboardPressed = false
    onEnabledChanged: if (!enabled)
        keyboardPressed = false

    Rectangle {
        anchors.fill: parent
        radius: Shell.Theme.radiusSmall
        color: root.pressed ? Shell.Theme.pressedSurface : root.hovered ? Shell.Theme.hoverSurface : root.checked || root.filled ? Shell.Theme.selectedSurface : "transparent"
        border.width: root.checked ? Shell.Theme.outlineWidth : 0
        border.color: Shell.Theme.systemAccent
    }

    RowLayout {
        id: content
        anchors.centerIn: parent
        spacing: Shell.Theme.spacingSmall

        Components.SemanticIcon {
            visible: root.icon.length > 0
            source: root.icon.length > 0 ? Qt.resolvedUrl("icons/" + root.icon + ".svg") : ""
            Layout.preferredWidth: Shell.Theme.iconMediumSize
            Layout.preferredHeight: Shell.Theme.iconMediumSize
            checked: root.checked
        }

        ColumnLayout {
            spacing: Shell.Theme.spacingXSmall
            Text {
                text: root.text
                color: root.enabled ? Shell.Theme.primaryText : Shell.Theme.secondaryText
                font.family: Shell.Theme.sansFont
                font.pixelSize: Shell.Theme.labelFontSize
                font.weight: Font.DemiBold
            }
            Text {
                visible: root.subtitle.length > 0
                text: root.subtitle
                color: Shell.Theme.secondaryText
                font.family: Shell.Theme.sansFont
                font.pixelSize: Shell.Theme.captionFontSize
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
        onClicked: root.clicked()
    }
    Components.Tooltip {
        visible: root.hovered && root.tooltipText.length > 0
        text: root.tooltipText
    }
}
