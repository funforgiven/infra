pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import ".." as Shell
import "../components" as Components
import "../services" as Services

Rectangle {
    id: root

    required property var dropdownHost
    property color accent: Shell.Theme.voiceAccent

    readonly property var inputs: Services.AudioService.physicalInputs
    readonly property var currentInput: Services.AudioService.defaultInput
    readonly property var actionState: ({
            pending: null,
            error: ""
        })
    readonly property bool expanded: dropdownHost !== null && dropdownHost.activeOutputPicker === root
    readonly property Item selectorAnchor: selector
    readonly property Component dropdownComponent: inputDropdownComponent
    readonly property int inputCount: inputs ? inputs.length : 0
    readonly property int rowContentHeight: 48
    readonly property int rowInset: Shell.Theme.spacingXSmall
    readonly property int rowHeight: rowContentHeight + rowInset * 2
    readonly property int rowSpacing: Shell.Theme.spacingXSmall
    readonly property int inputMarkerSize: 10
    readonly property int entryHorizontalPadding: Shell.Theme.spacingLarge
    readonly property int popupContentPadding: Shell.Theme.spacingMedium
    readonly property int minimumPopupWidth: 320
    readonly property int maximumPopupWidth: 680
    readonly property int visibleRowCount: Math.min(4, Math.max(1, inputCount))
    readonly property int desiredListHeight: inputCount === 0 ? 72 : visibleRowCount * rowHeight + Math.max(0, visibleRowCount - 1) * rowSpacing
    readonly property int desiredPopupHeight: popupContentPadding * 2 + desiredListHeight
    readonly property int desiredPopupWidth: root.contentDrivenPopupWidth()
    readonly property string selectorTitle: currentInput ? currentInput.label : "No default microphone"
    readonly property string selectorStatus: {
        if (currentInput && currentInput.available !== true)
            return "Default microphone unavailable";
        if (inputCount === 0)
            return "No microphones available";
        return "Default microphone";
    }

    function matchesCurrentInput(input) {
        return currentInput && input && String(currentInput.id) === String(input.id) && String(currentInput.serial) === String(input.serial);
    }

    function statusForInput(input) {
        if (matchesCurrentInput(input) && input && input.available !== true)
            return "Default · unavailable";
        if (matchesCurrentInput(input))
            return "Default";
        if (input && input.available !== true)
            return "Unavailable";
        return "";
    }

    function measuredInputRowWidth(input) {
        if (!input)
            return 0;
        var labelWidth = inputLabelMetrics.advanceWidth(input.label || "");
        var status = statusForInput(input);
        var statusWidth = status === "" ? 0 : Shell.Theme.spacingSmall + inputStatusMetrics.advanceWidth(status);
        return root.rowInset * 2 + root.entryHorizontalPadding * 2 + root.inputMarkerSize + Shell.Theme.spacingSmall + labelWidth + statusWidth;
    }

    function contentDrivenPopupWidth() {
        var rowWidth = 0;
        for (var index = 0; index < root.inputCount; index += 1)
            rowWidth = Math.max(rowWidth, root.measuredInputRowWidth(root.inputs[index]));
        return Math.ceil(Math.min(root.maximumPopupWidth, Math.max(root.minimumPopupWidth, rowWidth + root.popupContentPadding * 2)));
    }

    function openPopup() {
        if (expanded || dropdownHost === null)
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

    function activateInput(input) {
        if (!input || input.available !== true || matchesCurrentInput(input))
            return;
        if (Services.AudioService.selectDefaultInput(input.id, input.serial))
            closePopup(true);
    }

    onInputsChanged: {
        if (expanded && dropdownHost !== null)
            Qt.callLater(function () {
                root.dropdownHost.reconcileActiveOutputPicker(root);
            });
    }

    onCurrentInputChanged: {
        if (expanded && dropdownHost !== null)
            Qt.callLater(function () {
                root.dropdownHost.reconcileActiveOutputPicker(root);
            });
    }

    implicitHeight: 48 + Shell.Theme.spacingMedium * 2
    radius: Shell.Theme.radiusMedium
    color: Shell.Theme.baseSurface

    FontMetrics {
        id: inputLabelMetrics

        font.family: Shell.Theme.sansFont
        font.pixelSize: Shell.Theme.labelFontSize
        font.weight: Font.DemiBold
    }

    FontMetrics {
        id: inputStatusMetrics

        font.family: Shell.Theme.sansFont
        font.pixelSize: Shell.Theme.captionFontSize
        font.weight: Font.DemiBold
    }

    Item {
        id: selector

        anchors.fill: parent
        anchors.margins: Shell.Theme.spacingMedium
        activeFocusOnTab: true

        Accessible.name: "Default microphone, " + root.selectorTitle
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
            accent: root.accent
            radius: Shell.Theme.radiusSmall
            outlineWidth: 0
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Shell.Theme.spacingMedium
            anchors.rightMargin: Shell.Theme.spacingMedium
            spacing: Shell.Theme.spacingSmall

            Components.SemanticIcon {
                Layout.preferredWidth: Shell.Theme.iconLargeSize
                Layout.preferredHeight: Shell.Theme.iconLargeSize
                source: Quickshell.iconPath("audio-input-microphone-symbolic", "audio-input-microphone")
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1

                Text {
                    Layout.fillWidth: true
                    text: root.selectorTitle
                    color: root.currentInput && root.currentInput.available === true ? Shell.Theme.primaryText : Shell.Theme.errorText
                    elide: Text.ElideRight
                    font.family: Shell.Theme.sansFont
                    font.pixelSize: Shell.Theme.labelFontSize
                    font.weight: Font.DemiBold
                }

                Text {
                    Layout.fillWidth: true
                    text: root.selectorStatus
                    color: root.currentInput && root.currentInput.available !== true ? Shell.Theme.errorText : Shell.Theme.secondaryText
                    elide: Text.ElideRight
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
            accent: root.accent
            ringRadius: Shell.Theme.radiusSmall
        }

        MouseArea {
            id: selectorArea

            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.togglePopup()
        }
    }

    Component {
        id: inputDropdownComponent

        Rectangle {
            id: dropdownSurface

            function reconcileHighlightedOutput() {
                inputList.reconcileHighlighted();
            }

            function focusInitialInput() {
                inputList.focusInitial();
            }

            anchors.fill: parent
            color: Shell.Theme.elevatedSurface
            radius: Shell.Theme.radiusMedium
            border.width: Shell.Theme.outlineWidth
            border.color: Shell.Theme.outlineStrong
            focus: true

            Keys.onPressed: event => {
                if (event.key === Qt.Key_Escape) {
                    root.closePopup(true);
                    event.accepted = true;
                }
            }

            Component.onCompleted: Qt.callLater(dropdownSurface.focusInitialInput)

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
                onClicked: mouse => mouse.accepted = true
            }

            Item {
                anchors.fill: parent
                anchors.margins: root.popupContentPadding

                SelectableDeviceList {
                    id: inputList

                    anchors.fill: parent
                    candidates: root.inputs
                    currentDevice: root.currentInput
                    accent: root.accent
                    accessibleName: "Microphones"
                    emptyText: "No microphones available"
                    statusProvider: function (input) {
                        return root.statusForInput(input);
                    }
                    onActivated: input => root.activateInput(input)
                    onDismissRequested: root.closePopup(true)
                }
            }
        }
    }
}
