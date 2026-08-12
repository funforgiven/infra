pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import ".." as Shell
import "../components" as Components
import "../components/StableKeys.js" as StableKeys
import "../services" as Services

Rectangle {
    id: root

    required property color accent
    required property var dropdownHost
    property var groupKeys: []
    readonly property var currentInput: Services.AudioService.defaultInput
    readonly property var groups: Services.AudioService.captureGroups
    readonly property var inputAudio: currentInput && currentInput.node ? currentInput.node.audio : null
    readonly property bool inputMuted: inputAudio !== null && inputAudio.muted === true
    readonly property string inputStatus: {
        if (!Services.AudioService.ready)
            return "Binding input graph…";
        if (currentInput === null)
            return "No default microphone";
        if (currentInput.available !== true)
            return "Default microphone unavailable";
        return "";
    }

    function groupForKey(key) {
        return StableKeys.find(root.groups, key, function (group) {
            return group.key;
        });
    }

    function missingGroup(key) {
        return {
            key: String(key),
            canonicalId: "",
            displayName: "",
            iconPath: "",
            streams: [],
            streamRefs: [],
            count: 0,
            totalCount: 0
        };
    }

    function syncGroupKeys() {
        var next = StableKeys.reconcile(root.groupKeys, root.groups, function (group) {
            return group.key;
        });
        if (next !== root.groupKeys)
            root.groupKeys = next;
    }

    implicitWidth: 320
    implicitHeight: 660
    radius: Shell.Theme.radiusLarge
    color: Shell.Theme.baseSurface
    border.width: Shell.Theme.outlineWidth
    border.color: root.currentInput !== null && root.currentInput.available === true ? Shell.Theme.outline : Shell.Theme.error

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Shell.Theme.spacingLarge
        spacing: Shell.Theme.spacingMedium

        RowLayout {
            Layout.fillWidth: true
            spacing: Shell.Theme.spacingSmall

            Rectangle {
                Layout.preferredWidth: 46
                Layout.preferredHeight: 46
                radius: Shell.Theme.radiusMedium
                color: root.accent

                Text {
                    anchors.centerIn: parent
                    text: "mic"
                    color: Shell.Theme.accentText
                    font.family: "Material Symbols Rounded"
                    font.pixelSize: 28
                    font.weight: Font.Medium
                    Accessible.ignored: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1

                Text {
                    Layout.fillWidth: true
                    text: "Microphone"
                    color: Shell.Theme.primaryText
                    elide: Text.ElideRight
                    font.family: Shell.Theme.sansFont
                    font.pixelSize: Shell.Theme.titleFontSize
                    font.weight: Font.DemiBold
                }

                Text {
                    Layout.fillWidth: true
                    visible: root.inputStatus.length > 0
                    text: root.inputStatus
                    color: Services.AudioService.ready ? Shell.Theme.errorText : Shell.Theme.secondaryText
                    elide: Text.ElideRight
                    font.family: Shell.Theme.sansFont
                    font.pixelSize: Shell.Theme.captionFontSize
                }
            }

            Components.StatusChip {
                visible: root.currentInput !== null
                text: "Default"
                accent: root.accent
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: gainControls.implicitHeight + Shell.Theme.spacingMedium * 2
            radius: Shell.Theme.radiusMedium
            color: Shell.Theme.elevatedSurface

            RowLayout {
                id: gainControls

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Shell.Theme.spacingMedium
                spacing: Shell.Theme.spacingMedium

                InputGain {
                    Layout.fillWidth: true
                    input: root.currentInput
                    accent: root.accent
                }

                Components.IconButton {
                    Layout.preferredWidth: Shell.Theme.controlLargeSize
                    Layout.preferredHeight: Shell.Theme.controlLargeSize
                    Layout.alignment: Qt.AlignBottom
                    iconSource: Quickshell.iconPath(root.inputMuted ? "microphone-sensitivity-muted-symbolic" : "audio-input-microphone-symbolic", "audio-input-microphone")
                    iconSize: Shell.Theme.iconMediumSize
                    accessibleName: root.inputMuted ? "Unmute microphone" : "Mute microphone"
                    tooltipText: root.inputMuted ? "Unmute" : "Mute"
                    accent: root.accent
                    checked: root.inputMuted
                    enabled: root.inputAudio !== null
                    onClicked: button => {
                        if (button === Qt.LeftButton && root.currentInput)
                            Services.AudioActions.setInputMuted(root.currentInput.id, root.currentInput.serial, !root.inputMuted);
                    }
                }
            }
        }

        MicrophonePicker {
            Layout.fillWidth: true
            dropdownHost: root.dropdownHost
            accent: root.accent
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Shell.Theme.spacingXSmall

            Text {
                text: "Applications"
                color: Shell.Theme.secondaryText
                font.family: Shell.Theme.sansFont
                font.pixelSize: Shell.Theme.labelFontSize
                font.weight: Font.DemiBold
            }

            Item {
                Layout.fillWidth: true
            }

            Components.StatusChip {
                text: String(root.groups.length)
                accent: root.accent
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Flickable {
                id: streamView

                anchors.fill: parent
                anchors.rightMargin: streamScroll.visible ? Shell.Theme.spacingSmall : 0
                clip: true
                contentWidth: width
                contentHeight: streamColumn.implicitHeight
                boundsBehavior: Flickable.StopAtBounds

                ColumnLayout {
                    id: streamColumn

                    width: parent.width
                    spacing: Shell.Theme.spacingSmall

                    Repeater {
                        model: root.groupKeys

                        delegate: StreamCard {
                            required property string modelData
                            readonly property var liveGroup: root.groupForKey(modelData)

                            Layout.fillWidth: true
                            visible: liveGroup !== null
                            group: liveGroup || root.missingGroup(modelData)
                            accent: root.accent
                            draggable: false
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 64
                        visible: root.groups.length === 0
                        radius: Shell.Theme.radiusMedium
                        color: Shell.Theme.baseSurface

                        Text {
                            anchors.centerIn: parent
                            width: parent.width - Shell.Theme.spacingLarge * 2
                            text: "No applications recording"
                            color: Shell.Theme.secondaryText
                            horizontalAlignment: Text.AlignHCenter
                            font.family: Shell.Theme.sansFont
                            font.pixelSize: Shell.Theme.bodyFontSize
                        }
                    }
                }
            }

            Rectangle {
                id: streamScroll

                visible: streamView.contentHeight > streamView.height + 1
                anchors.right: parent.right
                width: 4
                height: visible ? Math.max(28, parent.height * parent.height / streamView.contentHeight) : 0
                y: visible ? (parent.height - height) * streamView.visibleArea.yPosition / Math.max(0.001, 1 - streamView.visibleArea.heightRatio) : 0
                radius: Shell.Theme.radiusPill
                color: Shell.Theme.outlineStrong
            }
        }
    }

    onGroupsChanged: syncGroupKeys()
    Component.onCompleted: syncGroupKeys()
}
