pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import ".." as Shell
import "../components" as Components
import "../services" as Services
import "OutputSelection.js" as OutputSelection

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

            Components.AppIcon {
                Layout.preferredWidth: Shell.Theme.iconLargeSize
                Layout.preferredHeight: Shell.Theme.iconLargeSize
                iconSize: Shell.Theme.iconMediumSize
                source: Quickshell.iconPath("audio-input-microphone-symbolic", "audio-input-microphone")
                accessibleName: "Microphone"
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

            property string highlightedOutputKey: ""

            function applyHighlightedSelection(selection, ensureVisible) {
                highlightedOutputKey = selection.key;
                inputList.currentIndex = selection.index;
                if (ensureVisible && selection.index >= 0)
                    inputList.positionViewAtIndex(selection.index, ListView.Contain);
            }

            function highlightInputAt(index, ensureVisible) {
                if (index < 0 || index >= root.inputCount)
                    return;
                applyHighlightedSelection({
                    index: index,
                    key: OutputSelection.outputKey(root.inputs[index]),
                    rehomed: false
                }, ensureVisible);
            }

            function reconcileHighlightedOutput() {
                var previousIndex = inputList.currentIndex;
                var selection = OutputSelection.reconcileSelection(root.inputs, highlightedOutputKey, root.currentInput);
                applyHighlightedSelection(selection, selection.rehomed || selection.index !== previousIndex);
            }

            function focusInitialInput() {
                var selection = OutputSelection.initialSelection(root.inputs, root.currentInput);
                applyHighlightedSelection(selection, true);
                if (selection.index >= 0)
                    inputList.forceActiveFocus();
                else
                    dropdownSurface.forceActiveFocus();
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

                ListView {
                    id: inputList

                    anchors.fill: parent
                    visible: root.inputCount > 0
                    clip: true
                    model: root.inputs
                    spacing: root.rowSpacing
                    boundsBehavior: Flickable.StopAtBounds
                    flickableDirection: Flickable.VerticalFlick
                    activeFocusOnTab: true

                    Accessible.name: "Microphones"
                    Accessible.role: Accessible.List

                    TapHandler {
                        id: inputListTap

                        acceptedButtons: Qt.LeftButton
                        gesturePolicy: TapHandler.DragThreshold
                        onPressedChanged: {
                            if (pressed)
                                inputList.cancelFlick();
                        }
                        onTapped: eventPoint => {
                            var index = OutputSelection.contentIndexAtGlobalPosition(inputList, eventPoint.globalPosition);
                            if (index < 0 || index >= root.inputCount)
                                return;
                            dropdownSurface.highlightInputAt(index, false);
                            root.activateInput(root.inputs[index]);
                        }
                    }

                    Keys.onPressed: event => {
                        if (event.key === Qt.Key_Escape) {
                            root.closePopup(true);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Up) {
                            dropdownSurface.highlightInputAt(Math.max(0, inputList.currentIndex - 1), true);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Down) {
                            dropdownSurface.highlightInputAt(Math.min(root.inputCount - 1, inputList.currentIndex + 1), true);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Home) {
                            if (root.inputCount > 0)
                                dropdownSurface.highlightInputAt(0, true);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_End) {
                            if (root.inputCount > 0)
                                dropdownSurface.highlightInputAt(root.inputCount - 1, true);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                            if (inputList.currentIndex >= 0 && inputList.currentIndex < root.inputCount)
                                root.activateInput(root.inputs[inputList.currentIndex]);
                            event.accepted = true;
                        }
                    }

                    delegate: Item {
                        id: inputRow

                        required property var modelData
                        required property int index

                        readonly property bool selected: root.matchesCurrentInput(modelData)
                        readonly property bool available: modelData.available === true
                        readonly property bool canActivate: available && !selected
                        readonly property bool keyboardSelected: ListView.isCurrentItem && inputList.activeFocus

                        width: ListView.view.width
                        height: root.rowHeight
                        opacity: available || selected ? 1 : Shell.Theme.disabledOpacity

                        function activate() {
                            if (canActivate)
                                root.activateInput(modelData);
                        }

                        Accessible.name: modelData.label
                        Accessible.description: selected ? "Default microphone" : (available ? "Available microphone; press to select" : "Unavailable microphone")
                        Accessible.focusable: true
                        Accessible.focused: keyboardSelected
                        Accessible.selectable: selected
                        Accessible.selected: selected
                        Accessible.role: canActivate ? Accessible.Button : Accessible.StaticText
                        Accessible.onPressAction: inputRow.activate()

                        Item {
                            anchors.fill: parent
                            anchors.margins: root.rowInset

                            Components.Surface {
                                anchors.fill: parent
                                interactive: true
                                hovered: inputHover.hovered || inputRow.keyboardSelected
                                pressed: inputListTap.pressed && inputList.currentIndex === inputRow.index
                                selected: inputRow.selected
                                accent: root.accent
                                radius: Shell.Theme.radiusSmall
                                outlineWidth: 0
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: root.entryHorizontalPadding
                                anchors.rightMargin: root.entryHorizontalPadding
                                spacing: Shell.Theme.spacingSmall

                                Rectangle {
                                    Layout.preferredWidth: root.inputMarkerSize
                                    Layout.preferredHeight: root.inputMarkerSize
                                    radius: Shell.Theme.radiusPill
                                    color: inputRow.available ? (inputRow.selected ? root.accent : Shell.Theme.secondaryText) : Shell.Theme.error
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: inputRow.modelData.label
                                    color: Shell.Theme.primaryText
                                    elide: Text.ElideRight
                                    font.family: Shell.Theme.sansFont
                                    font.pixelSize: Shell.Theme.labelFontSize
                                    font.weight: inputRow.selected ? Font.DemiBold : Font.Normal
                                }

                                Text {
                                    visible: root.statusForInput(inputRow.modelData).length > 0
                                    text: root.statusForInput(inputRow.modelData)
                                    color: inputRow.available ? (inputRow.selected ? Shell.Theme.primaryText : Shell.Theme.secondaryText) : Shell.Theme.errorText
                                    font.family: Shell.Theme.sansFont
                                    font.pixelSize: Shell.Theme.captionFontSize
                                    font.weight: inputRow.selected ? Font.DemiBold : Font.Normal
                                }
                            }

                            Components.FocusRing {
                                active: inputRow.keyboardSelected
                                accent: root.accent
                                ringRadius: Shell.Theme.radiusSmall
                            }

                            HoverHandler {
                                id: inputHover

                                cursorShape: inputRow.canActivate ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onHoveredChanged: {
                                    if (hovered)
                                        dropdownSurface.highlightInputAt(inputRow.index, false);
                                }
                            }
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    width: parent.width - Shell.Theme.spacingMedium * 2
                    visible: root.inputCount === 0
                    text: "No microphones available"
                    color: Shell.Theme.errorText
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font.family: Shell.Theme.sansFont
                    font.pixelSize: Shell.Theme.captionFontSize
                }
            }
        }
    }
}
