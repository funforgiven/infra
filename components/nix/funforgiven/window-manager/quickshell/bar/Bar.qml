pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import ".." as Shell
import "../components" as Components
import "../services" as Services

Scope {
    id: root

    signal mixerRequested(var anchorItem, var screen, real topInset)
    signal cameraRequested(var anchorItem, var screen, real topInset)

    Variants {
        model: Quickshell.screens

        delegate: PanelWindow {
            id: barWindow

            required property var modelData

            screen: modelData
            implicitHeight: 56
            color: "transparent"
            anchors {
                left: true
                right: true
                top: true
            }
            exclusiveZone: implicitHeight
            focusable: false
            aboveWindows: true
            WlrLayershell.namespace: "funforgiven:bar"
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

            Components.Surface {
                id: leftIsland

                readonly property real desiredWidth: workspaceTasks.implicitWidth + Shell.Theme.spacingXSmall * 2
                readonly property real availableWidth: Math.max(Shell.Theme.controlLargeSize, rightIsland.x - anchors.leftMargin - Shell.Theme.spacingMedium)

                anchors.left: parent.left
                anchors.leftMargin: Shell.Theme.spacingMedium
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(Math.max(desiredWidth, Shell.Theme.controlLargeSize), availableWidth)
                height: Shell.Theme.controlSize
                elevated: true
                radius: Shell.Theme.radiusPill

                WorkspaceStrip {
                    id: workspaceTasks

                    anchors.fill: parent
                    anchors.margins: Shell.Theme.spacingXSmall
                    outputName: barWindow.screen ? barWindow.screen.name : "" // qmllint disable missing-property
                }
            }

            Components.Surface {
                id: rightIsland
                anchors.right: parent.right
                anchors.rightMargin: Shell.Theme.spacingMedium
                anchors.verticalCenter: parent.verticalCenter
                width: implicitWidth
                height: Shell.Theme.controlSize
                implicitWidth: statusArea.implicitWidth + Shell.Theme.spacingXSmall * 2
                elevated: true
                radius: Shell.Theme.radiusPill

                Row {
                    id: statusArea

                    anchors.centerIn: parent
                    height: Shell.Theme.controlCompactSize
                    spacing: Shell.Theme.spacingXSmall

                    NiriStatus {
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Tray {
                        id: tray

                        height: parent.height
                        width: implicitWidth
                        parentWindow: barWindow
                    }

                    Row {
                        height: parent.height
                        spacing: 2

                        MixerButton {
                            id: mixerButton

                            height: parent.height
                            width: implicitWidth
                            groupPosition: "start"
                            checked: Services.PopupCoordinator.activeKind === "mixer" && Services.PopupCoordinator.activeScreen === barWindow.screen
                            tooltipSuppressed: checked
                            onRequested: {
                                root.mixerRequested(mixerButton, barWindow.screen, barWindow.height);
                            }
                        }

                        CameraButton {
                            id: cameraButton

                            height: parent.height
                            width: implicitWidth
                            groupPosition: "end"
                            tooltipSuppressed: Services.PopupCoordinator.activeKind === "camera" && Services.PopupCoordinator.activeScreen === barWindow.screen
                            onRequested: root.cameraRequested(cameraButton, barWindow.screen, barWindow.height)
                        }
                    }

                    Clock {
                        height: parent.height
                        width: implicitWidth
                    }

                    SessionControls {
                        height: parent.height
                        width: implicitWidth
                    }
                }
            }
        }
    }
}
