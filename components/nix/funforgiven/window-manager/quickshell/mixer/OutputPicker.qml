// Portions adapted from Avenge Media's MIT-licensed popup at commit
// d82d86df5cb932fc275dcf30c35cd72705a21065 and noctalia-dev's MIT-licensed
// popup at commit a48885b9fec485c903c955749a7da6e30147cd38.
// See THIRD_PARTY_NOTICES.md.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import ".." as Shell
import "../components" as Components
import "../services" as Services

Rectangle {
    id: root

    required property var channel
    required property var outputs
    required property color accent
    required property var dropdownHost

    readonly property bool expanded: dropdownHost !== null && dropdownHost.activeOutputPicker === root
    readonly property Item selectorAnchor: selector
    readonly property Component dropdownComponent: outputDropdownComponent

    readonly property var actionState: Services.AudioActions.channelState(channel.id)
    readonly property int outputCount: outputs ? outputs.length : 0
    readonly property int rowContentHeight: 48
    readonly property int rowInset: Shell.Theme.spacingXSmall
    readonly property int rowHeight: rowContentHeight + rowInset * 2
    readonly property int rowSpacing: Shell.Theme.spacingXSmall
    readonly property int outputMarkerSize: 10
    readonly property int entryHorizontalPadding: Shell.Theme.spacingLarge
    readonly property int popupContentPadding: Shell.Theme.spacingMedium
    readonly property int minimumPopupWidth: 280
    readonly property int maximumPopupWidth: 680
    readonly property int visibleRowCount: Math.min(4, Math.max(1, outputCount))
    readonly property int desiredListHeight: outputCount === 0 ? 72 : visibleRowCount * rowHeight + Math.max(0, visibleRowCount - 1) * rowSpacing
    readonly property int desiredPopupHeight: popupContentPadding * 2 + desiredListHeight + Shell.Theme.spacingSmall + Shell.Theme.controlLargeSize + (actionState.error !== "" ? 56 + Shell.Theme.spacingSmall : 0)
    readonly property int desiredPopupWidth: root.contentDrivenPopupWidth()
    readonly property string selectorTitle: channel.output ? channel.output.label : "No hardware target"
    readonly property string selectorStatus: {
        if (actionState.pending !== null)
            return actionState.pending.label;
        if (actionState.error !== "")
            return actionState.error;
        if (channel.output && channel.output.available !== true)
            return "Current output unavailable";
        if (channel.output)
            return "";
        if (outputCount === 0)
            return "No outputs available";
        return "Select an output";
    }

    function matchesCurrentOutput(output) {
        return channel.output && output && String(channel.output.id) === String(output.id) && String(channel.output.serial) === String(output.serial);
    }

    function statusForOutput(output) {
        if (matchesCurrentOutput(output) && output && output.available !== true)
            return "Current · unavailable";
        if (matchesCurrentOutput(output))
            return "Current";
        if (output && output.available !== true)
            return "Unavailable";
        return "";
    }

    function measuredOutputRowWidth(output) {
        if (!output)
            return 0;

        var labelWidth = outputLabelMetrics.advanceWidth(output.label || "");
        var status = statusForOutput(output);
        var statusWidth = status === "" ? 0 : Shell.Theme.spacingSmall + outputStatusMetrics.advanceWidth(status);
        return root.rowInset * 2 + root.entryHorizontalPadding * 2 + root.outputMarkerSize + Shell.Theme.spacingSmall + labelWidth + statusWidth;
    }

    function contentDrivenPopupWidth() {
        var rowWidth = 0;
        for (var index = 0; index < root.outputCount; index += 1)
            rowWidth = Math.max(rowWidth, root.measuredOutputRowWidth(root.outputs[index]));
        return Math.ceil(Math.min(root.maximumPopupWidth, Math.max(root.minimumPopupWidth, rowWidth + root.popupContentPadding * 2)));
    }

    function openPopup() {
        if (actionState.pending !== null || expanded || dropdownHost === null)
            return;
        dropdownHost.openOutputPicker(root);
    }

    function closePopup(restoreFocus) {
        if (dropdownHost !== null)
            dropdownHost.closeOutputPicker(root, restoreFocus === true);
    }

    function togglePopup() {
        if (expanded)
            closePopup(true);
        else
            openPopup();
    }

    function restoreSelectorFocus() {
        Qt.callLater(function () {
            if (selector.visible && selector.enabled)
                selector.forceActiveFocus();
        });
    }

    function activateOutput(output) {
        if (!output || !output.available || matchesCurrentOutput(output) || actionState.pending !== null)
            return;
        if (Services.AudioActions.moveBridge(channel.id, output.id, output.serial))
            closePopup(true);
    }

    function forgetOutput() {
        if (actionState.pending !== null || channel.bridge === null)
            return;
        if (Services.AudioActions.forgetBridgeTarget(channel.id))
            closePopup(true);
    }

    onActionStateChanged: {
        if (actionState.pending !== null && expanded)
            closePopup(false);
    }

    onOutputsChanged: {
        if (expanded && dropdownHost !== null)
            Qt.callLater(function () {
                root.dropdownHost.reconcileActiveOutputPicker(root);
            });
    }

    implicitHeight: pickerContent.implicitHeight + Shell.Theme.spacingMedium * 2
    radius: Shell.Theme.radiusMedium
    color: Shell.Theme.baseSurface
    border.width: actionState.error !== "" ? Shell.Theme.outlineWidth : 0
    border.color: Shell.Theme.error

    FontMetrics {
        id: outputLabelMetrics

        font.family: Shell.Theme.sansFont
        font.pixelSize: Shell.Theme.labelFontSize
        font.weight: Font.DemiBold
    }

    FontMetrics {
        id: outputStatusMetrics

        font.family: Shell.Theme.sansFont
        font.pixelSize: Shell.Theme.captionFontSize
        font.weight: Font.DemiBold
    }

    ColumnLayout {
        id: pickerContent

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Shell.Theme.spacingMedium
        spacing: Shell.Theme.spacingSmall

        Item {
            id: selector

            Layout.fillWidth: true
            implicitHeight: 48
            activeFocusOnTab: enabled
            enabled: root.actionState.pending === null

            Accessible.name: "Hardware output, " + root.selectorTitle
            Accessible.description: root.selectorStatus
            Accessible.role: Accessible.Button
            Accessible.onPressAction: root.togglePopup()

            Keys.onPressed: event => {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                    root.togglePopup();
                    event.accepted = true;
                } else if (event.key === Qt.Key_Escape && root.expanded) {
                    root.closePopup(true);
                    event.accepted = true;
                }
            }

            Components.Surface {
                anchors.fill: parent
                elevated: true
                interactive: true
                hovered: selectorArea.containsMouse
                pressed: selectorArea.pressed
                selected: root.expanded
                accent: root.actionState.error !== "" ? Shell.Theme.error : root.accent
                outlineColor: root.actionState.error !== "" ? Shell.Theme.error : Shell.Theme.outline
                outlineWidth: root.actionState.error !== "" ? Shell.Theme.outlineWidth : 0
                radius: Shell.Theme.radiusSmall
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Shell.Theme.spacingMedium
                anchors.rightMargin: Shell.Theme.spacingMedium
                spacing: Shell.Theme.spacingSmall

                Components.SemanticIcon {
                    Layout.preferredWidth: Shell.Theme.iconLargeSize
                    Layout.preferredHeight: Shell.Theme.iconLargeSize
                    source: Quickshell.iconPath("audio-card-symbolic", "audio-card")
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1

                    Text {
                        Layout.fillWidth: true
                        text: root.selectorTitle
                        color: root.channel.output && root.channel.output.available === true ? Shell.Theme.primaryText : Shell.Theme.errorText
                        elide: Text.ElideRight
                        font.family: Shell.Theme.sansFont
                        font.pixelSize: Shell.Theme.labelFontSize
                        font.weight: Font.DemiBold
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: root.selectorStatus.length > 0
                        text: root.selectorStatus
                        color: root.actionState.pending !== null ? Shell.Theme.warningText : (root.actionState.error !== "" || (root.channel.output && root.channel.output.available !== true) ? Shell.Theme.errorText : Shell.Theme.secondaryText)
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font.family: Shell.Theme.sansFont
                        font.pixelSize: Shell.Theme.captionFontSize
                    }
                }

                Text {
                    text: root.expanded ? "▴" : "▾"
                    color: Shell.Theme.secondaryText
                    font.pixelSize: Shell.Theme.iconSmallSize
                }
            }

            Components.FocusRing {
                active: selector.activeFocus
                accent: root.actionState.error !== "" ? Shell.Theme.error : root.accent
                ringRadius: Shell.Theme.radiusSmall
            }

            MouseArea {
                id: selectorArea

                anchors.fill: parent
                enabled: selector.enabled
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.togglePopup()
            }
        }
    }

    Component {
        id: outputDropdownComponent

        Rectangle {
            id: dropdownSurface

            function reconcileHighlightedOutput() {
                deviceList.reconcileHighlighted();
            }

            function focusInitialOutput() {
                deviceList.focusInitial();
            }

            anchors.fill: parent
            color: Shell.Theme.elevatedSurface
            radius: Shell.Theme.radiusMedium
            border.width: Shell.Theme.outlineWidth
            border.color: root.actionState.error !== "" ? Shell.Theme.error : Shell.Theme.outlineStrong
            focus: true

            Keys.onPressed: event => {
                if (event.key === Qt.Key_Escape) {
                    root.closePopup(true);
                    event.accepted = true;
                }
            }

            Component.onCompleted: Qt.callLater(dropdownSurface.focusInitialOutput)

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
                onClicked: mouse => mouse.accepted = true
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: root.popupContentPadding
                spacing: Shell.Theme.spacingSmall

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: visible ? 56 : 0
                    visible: root.actionState.error !== ""
                    radius: Shell.Theme.radiusSmall
                    color: Shell.Theme.errorSurface

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Shell.Theme.spacingMedium
                        anchors.rightMargin: Shell.Theme.spacingXSmall
                        spacing: Shell.Theme.spacingSmall

                        Text {
                            Layout.fillWidth: true
                            text: root.actionState.error
                            color: Shell.Theme.errorText
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                            font.family: Shell.Theme.sansFont
                            font.pixelSize: Shell.Theme.captionFontSize
                        }

                        Components.IconButton {
                            label: "×"
                            accessibleName: "Dismiss output error"
                            tooltipText: "Dismiss"
                            attention: true
                            accent: Shell.Theme.error
                            onClicked: Services.AudioActions.dismissChannelError(root.channel.id)
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: root.desiredListHeight

                    SelectableDeviceList {
                        id: deviceList

                        anchors.fill: parent
                        candidates: root.outputs
                        currentDevice: root.channel.output
                        accent: root.accent
                        busy: root.actionState.pending !== null
                        accessibleName: "Hardware outputs"
                        emptyText: "No outputs available"
                        statusProvider: function (output) {
                            return root.statusForOutput(output);
                        }
                        onActivated: output => root.activateOutput(output)
                        onDismissRequested: root.closePopup(true)
                    }
                }

                Components.ActionButton {
                    Layout.alignment: Qt.AlignRight
                    text: "Auto-select"
                    variant: "text"
                    enabled: root.actionState.pending === null && root.channel.bridge !== null
                    onClicked: root.forgetOutput()
                }
            }
        }
    }
}
