pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Wayland
import ".." as Shell
import "../components" as Components
import "../services" as Services

Scope {
    id: root

    property Item anchorItem: null
    property var selectedScreen: null
    property real topInset: 56
    property bool opened: false
    property int coordinatorToken: 0
    readonly property bool visible: cameraWindow.visible
    readonly property rect panelRect: Qt.rect(surface.x, surface.y, surface.width, surface.height)
    readonly property var camera: Services.CameraService
    property int section: 0
    readonly property var sections: [
        {
            label: "Framing",
            icon: "move"
        },
        {
            label: "Exposure",
            icon: "sun"
        },
        {
            label: "Color",
            icon: "palette"
        },
        {
            label: "Focus",
            icon: "focus"
        }
    ]
    readonly property var settingsGroups: section === 1 ? [
        {
            title: "Exposure",
            icon: "sun",
            keys: ["auto_exposure", "exposure_time_absolute", "gain", "backlight_compensation"],
            hdr: true
        },
        {
            title: "White balance",
            icon: "thermometer",
            keys: ["white_balance_automatic", "white_balance_temperature", "red_balance", "blue_balance"]
        }
    ] : section === 2 ? [
        {
            title: "Tone",
            icon: "sliders-horizontal",
            keys: ["brightness", "contrast", "saturation"]
        },
        {
            title: "Detail",
            icon: "palette",
            keys: ["sharpness", "hue", "power_line_frequency"]
        }
    ] : [
        {
            title: "Focus",
            icon: "focus",
            keys: ["focus_automatic_continuous", "focus_absolute"]
        }
    ]

    function icon(name) {
        return Qt.resolvedUrl("icons/" + name + ".svg");
    }

    function toggleAt(item, screen, inset) {
        if (opened && anchorItem === item && selectedScreen === screen) {
            dismiss();
            return;
        }
        anchorItem = item;
        selectedScreen = screen;
        topInset = inset;
        coordinatorToken = Services.PopupCoordinator.open("camera", root, screen);
        opened = true;
        Services.PopupCoordinator.markOpen(root, coordinatorToken);
    }

    function dismiss() {
        Services.PopupCoordinator.beginClose(root, coordinatorToken);
        opened = false;
        Services.PopupCoordinator.finishClose(root, coordinatorToken);
        coordinatorToken = 0;
    }

    function closeFromCoordinator(token, reason) {
        void reason;
        if (token === coordinatorToken)
            dismiss();
    }

    onOpenedChanged: camera.watching = opened
    onSelectedScreenChanged: {
        if (opened && selectedScreen === null)
            dismiss();
    }
    Component.onDestruction: Services.PopupCoordinator.ownerDestroyed(root)

    Shortcut {
        sequence: "Escape"
        enabled: root.opened
        onActivated: root.dismiss()
    }

    PanelWindow { // qmllint disable uncreatable-type
        id: cameraWindow

        screen: root.selectedScreen
        visible: root.opened && root.selectedScreen !== null
        color: "transparent"
        exclusiveZone: 0
        exclusionMode: ExclusionMode.Ignore
        focusable: true
        aboveWindows: true
        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }
        WlrLayershell.namespace: "funforgiven:camera"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onPressed: root.dismiss()
        }

        Components.Surface {
            id: surface

            width: Math.min(root.camera.awake ? 680 : 400, Math.max(1, cameraWindow.width - Shell.Theme.spacingLarge * 2))
            height: Math.min(main.implicitHeight + Shell.Theme.spacingLarge * 2, Math.max(1, cameraWindow.height - root.topInset - Shell.Theme.spacingLarge))
            x: Math.max(Shell.Theme.spacingLarge, cameraWindow.width - width - Shell.Theme.spacingLarge)
            y: root.topInset + Shell.Theme.spacingXSmall
            elevated: true
            radius: Shell.Theme.radiusLarge
            outlineColor: Shell.Theme.outlineStrong

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
            }

            ColumnLayout {
                id: main
                anchors.fill: parent
                anchors.margins: Shell.Theme.spacingLarge
                spacing: Shell.Theme.spacingMedium

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Shell.Theme.spacingMedium

                    Components.SemanticIcon {
                        source: root.icon("webcam")
                        Layout.preferredWidth: Shell.Theme.iconLargeSize
                        Layout.preferredHeight: Shell.Theme.iconLargeSize
                        active: root.camera.awake
                    }
                    ColumnLayout {
                        spacing: 2
                        Text {
                            text: "OBSBOT Tiny 3"
                            color: Shell.Theme.primaryText
                            font.family: Shell.Theme.sansFont
                            font.pixelSize: Shell.Theme.titleFontSize
                            font.weight: Font.DemiBold
                        }
                        RowLayout {
                            spacing: Shell.Theme.spacingXSmall
                            Rectangle {
                                width: 5
                                height: 5
                                radius: 3
                                color: root.camera.awake ? Shell.Theme.success : Shell.Theme.tertiaryText
                            }
                            Text {
                                text: root.camera.state.connected !== true ? "Disconnected" : root.camera.busy ? "Updating…" : root.camera.awake ? "Ready" : "Sleeping"
                                color: Shell.Theme.secondaryText
                                font.family: Shell.Theme.sansFont
                                font.pixelSize: Shell.Theme.captionFontSize
                            }
                        }
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Components.IconButton {
                        iconSource: root.icon("power")
                        accessibleName: root.camera.awake ? "Put camera to sleep" : "Wake camera"
                        checked: root.camera.awake
                        enabled: root.camera.state.connected === true && !root.camera.busy
                        onClicked: root.camera.request(root.camera.awake ? "sleep" : "wake")
                    }
                    Components.IconButton {
                        iconSource: root.icon("x")
                        accessibleName: "Close camera controls"
                        onClicked: root.dismiss()
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Shell.Theme.controlSize + Shell.Theme.spacingXSmall * 2
                    visible: root.camera.awake
                    radius: Shell.Theme.radiusMedium
                    color: Shell.Theme.baseSurface
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: Shell.Theme.spacingXSmall
                        spacing: Shell.Theme.spacingXSmall
                        Repeater {
                            model: root.sections
                            delegate: CameraAction {
                                id: tab
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                text: tab.modelData.label
                                icon: tab.modelData.icon
                                checked: root.section === tab.index
                                tooltipText: ""
                                onClicked: root.section = tab.index
                            }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: root.camera.error || root.camera.state.error || root.camera.state.profileError || root.camera.state.settingsError || ""
                    color: Shell.Theme.error
                    font.family: Shell.Theme.sansFont
                    font.pixelSize: Shell.Theme.captionFontSize
                    wrapMode: Text.WordWrap
                }

                Flickable {
                    id: viewport
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: body.implicitHeight
                    contentWidth: width
                    contentHeight: body.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    Controls.ScrollBar.vertical: Controls.ScrollBar {
                        policy: Controls.ScrollBar.AsNeeded
                    }

                    ColumnLayout {
                        id: body
                        width: viewport.width
                        spacing: Shell.Theme.spacingMedium

                        Item {
                            Layout.fillWidth: true
                            visible: !root.camera.awake
                            implicitHeight: 80
                            CameraAction {
                                anchors.centerIn: parent
                                text: root.camera.state.connected === true ? "Wake camera" : "Camera disconnected"
                                icon: root.camera.state.connected === true ? "power" : "webcam"
                                filled: true
                                enabled: root.camera.state.connected === true && !root.camera.busy
                                onClicked: root.camera.request("wake")
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.camera.awake && root.section === 0
                            spacing: Shell.Theme.spacingMedium

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Shell.Theme.spacingMedium
                                CameraGroup {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.fillHeight: true
                                    title: "Pan & tilt"
                                    icon: "move"
                                    Item {
                                        Layout.fillWidth: true
                                        implicitHeight: 168
                                        Rectangle {
                                            width: 160
                                            height: 160
                                            anchors.centerIn: parent
                                            radius: 80
                                            color: Shell.Theme.elevatedSurface
                                            border.color: Shell.Theme.outline
                                            border.width: Shell.Theme.outlineWidth
                                            enabled: root.camera.awake && !root.camera.busy
                                            Repeater {
                                                model: [
                                                    {
                                                        direction: "up",
                                                        icon: "chevron-up",
                                                        x: 60,
                                                        y: 8
                                                    },
                                                    {
                                                        direction: "left",
                                                        icon: "chevron-left",
                                                        x: 8,
                                                        y: 60
                                                    },
                                                    {
                                                        direction: "right",
                                                        icon: "chevron-right",
                                                        x: 112,
                                                        y: 60
                                                    },
                                                    {
                                                        direction: "down",
                                                        icon: "chevron-down",
                                                        x: 60,
                                                        y: 112
                                                    }
                                                ]
                                                delegate: Components.IconButton {
                                                    id: directionButton
                                                    required property var modelData
                                                    width: 40
                                                    height: 40
                                                    x: directionButton.modelData.x
                                                    y: directionButton.modelData.y
                                                    iconSource: root.icon(directionButton.modelData.icon)
                                                    accessibleName: "Tilt / pan " + directionButton.modelData.direction
                                                    tooltipText: "Move " + directionButton.modelData.direction
                                                    onClicked: root.camera.request("nudge", {
                                                        direction: directionButton.modelData.direction
                                                    })
                                                }
                                            }
                                            Components.IconButton {
                                                anchors.centerIn: parent
                                                width: 44
                                                height: 44
                                                iconSource: root.icon("crosshair")
                                                accessibleName: "Reset camera to center"
                                                tooltipText: "Center camera"
                                                onClicked: root.camera.request("center")
                                            }
                                        }
                                    }
                                }
                                CameraGroup {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.fillHeight: true
                                    title: "Framing"
                                    icon: "scan-face"
                                    CameraToggle {
                                        Layout.fillWidth: true
                                        text: "Human tracking"
                                        icon: "scan-face"
                                        checked: root.camera.state.tracking === true
                                        enabled: root.camera.awake && !root.camera.busy
                                        onToggled: root.camera.request("tracking", {
                                            value: root.camera.state.tracking !== true
                                        })
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        height: 1
                                        color: Shell.Theme.outline
                                    }
                                    CameraControl {
                                        Layout.fillWidth: true
                                        visible: root.camera.state.controls.zoom_absolute !== undefined
                                        controlKey: "zoom_absolute"
                                        control: root.camera.state.controls.zoom_absolute || {
                                            name: "Zoom",
                                            type: 1,
                                            value: null,
                                            default: 0,
                                            minimum: 0,
                                            maximum: 100,
                                            step: 1
                                        }
                                    }
                                    Item {
                                        Layout.fillHeight: true
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: Shell.Theme.spacingSmall
                                Repeater {
                                    model: root.camera.state.presets || []
                                    delegate: Components.Surface {
                                        id: preset
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: 1
                                        implicitHeight: 66
                                        outlineWidth: 0
                                        radius: Shell.Theme.radiusSmall
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.rightMargin: Shell.Theme.spacingXSmall
                                            spacing: 0
                                            CameraAction {
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                text: ({
                                                        call: "Normal call",
                                                        close: "Close-up",
                                                        standing: "Wide standing"
                                                    })[preset.modelData.id] || preset.modelData.label
                                                icon: ({
                                                        call: "video",
                                                        close: "user-round",
                                                        standing: "person-standing"
                                                    })[preset.modelData.id] || "video"
                                                subtitle: preset.modelData.saved ? "Recall" : "Not saved"
                                                tooltipText: "Recall framing and image settings"
                                                enabled: root.camera.awake && preset.modelData.saved === true && !root.camera.busy
                                                onClicked: root.camera.request("recall-preset", {
                                                    preset: preset.modelData.id
                                                })
                                            }
                                            Components.IconButton {
                                                iconSource: root.icon("save")
                                                iconSize: Shell.Theme.iconSmallSize
                                                accessibleName: "Save " + preset.modelData.label + " preset"
                                                tooltipText: root.camera.state.tracking === true ? "Turn tracking off to save" : preset.modelData.saved ? "Replace saved preset" : "Save current framing and image"
                                                enabled: root.camera.awake && root.camera.state.positionReadable === true && root.camera.state.tracking !== true && !root.camera.busy
                                                onClicked: root.camera.request("save-preset", {
                                                    preset: preset.modelData.id
                                                })
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            visible: root.camera.awake && root.section !== 0
                            columns: root.section === 3 ? 1 : 2
                            columnSpacing: Shell.Theme.spacingMedium
                            rowSpacing: Shell.Theme.spacingMedium
                            Repeater {
                                model: root.settingsGroups
                                delegate: CameraGroup {
                                    id: settingsGroup
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.alignment: Qt.AlignTop
                                    title: settingsGroup.modelData.title
                                    icon: settingsGroup.modelData.icon
                                    Repeater {
                                        model: settingsGroup.modelData.keys.filter(key => root.camera.state.controls[key] !== undefined)
                                        delegate: CameraControl {
                                            id: setting
                                            required property string modelData
                                            Layout.fillWidth: true
                                            controlKey: setting.modelData
                                            control: root.camera.state.controls[setting.modelData] || {
                                                name: setting.modelData,
                                                type: 1,
                                                value: null
                                            }
                                        }
                                    }
                                    CameraToggle {
                                        Layout.fillWidth: true
                                        visible: settingsGroup.modelData.hdr === true
                                        text: "HDR"
                                        checked: root.camera.state.hdr === true
                                        enabled: root.camera.awake && !root.camera.busy
                                        onToggled: root.camera.request("hdr", {
                                            value: root.camera.state.hdr !== true
                                        })
                                    }
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Shell.Theme.spacingSmall
                    Components.SemanticIcon {
                        source: root.icon("mic-off")
                        Layout.preferredWidth: Shell.Theme.iconSmallSize
                        Layout.preferredHeight: Shell.Theme.iconSmallSize
                        muted: root.camera.privateAudio
                        warning: !root.camera.privateAudio
                    }
                    Text {
                        text: root.camera.privateAudio ? "Mic off" : "Privacy unconfirmed"
                        color: root.camera.privateAudio ? Shell.Theme.secondaryText : Shell.Theme.warningText
                        font.family: Shell.Theme.sansFont
                        font.pixelSize: Shell.Theme.captionFontSize
                    }
                    Components.SemanticIcon {
                        visible: root.camera.privateAudio
                        source: root.icon("speech")
                        Layout.leftMargin: Shell.Theme.spacingSmall
                        Layout.preferredWidth: Shell.Theme.iconSmallSize
                        Layout.preferredHeight: Shell.Theme.iconSmallSize
                        muted: true
                    }
                    Text {
                        visible: root.camera.privateAudio
                        text: "Voice off"
                        color: Shell.Theme.secondaryText
                        font.family: Shell.Theme.sansFont
                        font.pixelSize: Shell.Theme.captionFontSize
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Text {
                        visible: root.camera.awake && root.section !== 0
                        text: "Auto-saved"
                        color: Shell.Theme.tertiaryText
                        font.family: Shell.Theme.sansFont
                        font.pixelSize: Shell.Theme.captionFontSize
                    }
                }
            }
        }
    }
}
