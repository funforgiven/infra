import QtQuick
import Quickshell.Widgets
import ".." as Shell

Item {
    id: root

    property string iconSource: ""
    property string label: ""
    property string accessibleName: label
    property string tooltipText: accessibleName
    property color accent: Shell.Theme.systemAccent
    property bool tintIcon: true
    property bool checked: false
    property bool attention: false
    property bool warningIcon: false
    property bool destructive: false
    property bool hovered: pointer.containsMouse
    property int iconSize: Shell.Theme.iconMediumSize
    property bool keyboardPressed: false
    // Position inside a connected button group: "single", "start", "middle",
    // or "end". Joined edges keep a small radius while outer edges morph.
    property string groupPosition: "single"
    // Set while this button's own popup is open so its tooltip does not
    // cover the popup.
    property bool tooltipSuppressed: false

    readonly property bool pressed: pointer.pressed || keyboardPressed
    readonly property color backgroundColor: {
        if (!enabled)
            return "transparent";
        if (attention)
            return Shell.Theme.errorSurface;
        if (checked && destructive)
            return Shell.Theme.errorSurface;
        if (checked)
            return pressed ? Qt.darker(Shell.Theme.selectedSurface, 1.08) : Shell.Theme.selectedSurface;
        if (pressed)
            return Shell.Theme.pressedSurface;
        if (hovered)
            return Shell.Theme.hoverSurface;
        return "transparent";
    }
    // Material 3 Expressive shape morph: round at rest, a rounded square when
    // selected, and tighter still while pressed.
    readonly property real shapeRadius: {
        if (pressed)
            return Shell.Theme.radiusXSmall;
        if (checked)
            return Shell.Theme.radiusSmall;
        return Math.min(width, height) / 2;
    }
    readonly property real joinedRadius: Shell.Theme.radiusXSmall / 2
    readonly property bool joinedStart: groupPosition === "middle" || groupPosition === "end"
    readonly property bool joinedEnd: groupPosition === "start" || groupPosition === "middle"
    property real animatedRadius: shapeRadius

    signal clicked(int button)
    signal wheel(int delta, bool horizontal)

    implicitWidth: Shell.Theme.controlCompactSize
    implicitHeight: Shell.Theme.controlCompactSize
    activeFocusOnTab: true
    scale: pressed ? Shell.Theme.pressedScale : 1

    Accessible.name: accessibleName
    Accessible.role: Accessible.Button
    Accessible.onPressAction: {
        if (root.enabled)
            root.clicked(Qt.LeftButton);
    }

    Keys.onPressed: event => {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            root.keyboardPressed = true;
            event.accepted = true;
        }
    }

    Keys.onReleased: event => {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            if (root.keyboardPressed)
                root.clicked(Qt.LeftButton);
            root.keyboardPressed = false;
            event.accepted = true;
        }
    }

    onEnabledChanged: {
        if (!enabled)
            keyboardPressed = false;
    }
    onActiveFocusChanged: {
        if (!activeFocus)
            keyboardPressed = false;
    }

    Behavior on scale {
        NumberAnimation {
            duration: Shell.Theme.animationNormal
            easing.type: Easing.BezierSpline
            easing.bezierCurve: Shell.Theme.curveSpatial
        }
    }

    Behavior on animatedRadius {
        NumberAnimation {
            duration: Shell.Theme.animationNormal
            easing.type: Easing.BezierSpline
            easing.bezierCurve: Shell.Theme.curveSpatial
        }
    }

    Rectangle {
        readonly property real outerRadius: Math.max(0, root.animatedRadius)
        readonly property real startRadius: root.joinedStart ? Math.min(outerRadius, root.joinedRadius) : outerRadius
        readonly property real endRadius: root.joinedEnd ? Math.min(outerRadius, root.joinedRadius) : outerRadius

        anchors.fill: parent
        color: root.backgroundColor
        topLeftRadius: startRadius
        bottomLeftRadius: startRadius
        topRightRadius: endRadius
        bottomRightRadius: endRadius

        Behavior on color {
            ColorAnimation {
                duration: Shell.Theme.animationFast
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Shell.Theme.curveEffects
            }
        }
    }

    IconImage {
        visible: root.iconSource.length > 0 && !root.tintIcon
        anchors.centerIn: parent
        width: root.iconSize
        height: root.iconSize
        source: root.tintIcon ? "" : root.iconSource
        mipmap: true
        opacity: root.enabled ? 1 : Shell.Theme.disabledOpacity

        Behavior on opacity {
            NumberAnimation {
                duration: Shell.Theme.animationFast
            }
        }
    }

    SemanticIcon {
        visible: root.iconSource.length > 0 && root.tintIcon
        anchors.centerIn: parent
        width: root.iconSize
        height: root.iconSize
        source: root.tintIcon ? root.iconSource : ""
        enabled: root.enabled
        hovered: root.hovered
        pressed: root.pressed
        checked: root.checked
        attention: root.attention
        warning: root.warningIcon
        destructive: root.destructive || root.attention
    }

    Text {
        visible: root.iconSource.length === 0
        anchors.centerIn: parent
        color: root.enabled ? Shell.Theme.primaryText : Shell.Theme.secondaryText
        text: root.label
        font.family: Shell.Theme.sansFont
        font.pixelSize: Shell.Theme.labelFontSize
        font.weight: Font.DemiBold
        opacity: root.enabled ? 1 : Shell.Theme.disabledOpacity
    }

    FocusRing {
        active: root.activeFocus
        accent: root.accent
        ringRadius: root.animatedRadius + 2
    }

    MouseArea {
        id: pointer

        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: mouse => root.clicked(mouse.button)
        onWheel: wheel => {
            const horizontal = Math.abs(wheel.angleDelta.x) > Math.abs(wheel.angleDelta.y);
            const angled = horizontal ? wheel.angleDelta.x : wheel.angleDelta.y;
            const pixel = horizontal ? wheel.pixelDelta.x : wheel.pixelDelta.y;
            root.wheel(angled !== 0 ? angled : pixel, horizontal);
            wheel.accepted = true;
        }
    }

    Tooltip {
        visible: root.hovered && !root.pressed && !root.tooltipSuppressed && root.tooltipText.length > 0
        text: root.tooltipText
    }
}
