pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import ".." as Shell
import "../components" as Components
import "OutputSelection.js" as OutputSelection

Item {
    id: root

    required property var candidates
    required property var currentDevice
    property color accent: Shell.Theme.systemAccent
    property bool busy: false
    property string accessibleName: "Audio devices"
    property string emptyText: "No devices available"
    property var statusProvider: function (device) {
        void device;
        return "";
    }
    property string highlightedKey: ""
    property string hoveredKey: ""
    property point lastPointerPosition: Qt.point(-1, -1)
    property bool pointerPositionKnown: false
    property alias view: deviceList

    readonly property int candidateCount: candidates ? candidates.length : 0
    readonly property int rowContentHeight: 48
    readonly property int rowInset: Shell.Theme.spacingXSmall
    readonly property int rowHeight: rowContentHeight + rowInset * 2
    readonly property int rowSpacing: Shell.Theme.spacingXSmall
    readonly property int markerSize: 10
    readonly property int horizontalPadding: Shell.Theme.spacingLarge

    signal activated(var device)
    signal dismissRequested

    function keyFor(device) {
        return OutputSelection.outputKey(device);
    }

    function isCurrent(device) {
        var key = root.keyFor(device);
        return key !== "" && key === root.keyFor(root.currentDevice);
    }

    function canActivate(device) {
        return !root.busy && device && device.available === true && !root.isCurrent(device);
    }

    function statusFor(device) {
        return typeof root.statusProvider === "function" ? String(root.statusProvider(device) || "") : "";
    }

    function applySelection(selection, ensureVisible) {
        root.highlightedKey = selection.key;
        deviceList.currentIndex = selection.index;
        if (ensureVisible && selection.index >= 0)
            deviceList.positionViewAtIndex(selection.index, ListView.Contain);
    }

    function highlightAt(index, ensureVisible) {
        if (index < 0 || index >= root.candidateCount)
            return;
        root.applySelection({
            index: index,
            key: root.keyFor(root.candidates[index]),
            rehomed: false
        }, ensureVisible);
    }

    function reconcileHighlighted() {
        var previousIndex = deviceList.currentIndex;
        var selection = OutputSelection.reconcileSelection(root.candidates, root.highlightedKey, root.currentDevice);
        root.applySelection(selection, selection.rehomed || selection.index !== previousIndex);
    }

    function keyAtViewportPosition(position) {
        if (!root.pointerPositionKnown || position.x < 0 || position.y < 0 || position.x >= deviceList.width || position.y >= deviceList.height)
            return "";
        var index = deviceList.indexAt(position.x, deviceList.contentY + position.y);
        if (index < 0 || index >= root.candidateCount)
            return "";
        return root.keyFor(root.candidates[index]);
    }

    function rememberPointer(position) {
        root.lastPointerPosition = position;
        root.pointerPositionKnown = true;
        root.syncStationaryHover();
    }

    function syncStationaryHover() {
        root.hoveredKey = root.keyAtViewportPosition(root.lastPointerPosition);
        var index = OutputSelection.indexForKey(root.candidates, root.hoveredKey);
        if (index >= 0)
            root.highlightAt(index, false);
    }

    function forgetPointerFor(key) {
        if (root.hoveredKey !== key)
            return;
        root.hoveredKey = "";
        root.pointerPositionKnown = false;
        root.lastPointerPosition = Qt.point(-1, -1);
    }

    function focusInitial() {
        root.applySelection(OutputSelection.initialSelection(root.candidates, root.currentDevice), true);
        deviceList.forceActiveFocus();
    }

    function activateStableKey(pressedKey, delegateKey) {
        var activation = OutputSelection.activationCandidate(root.candidates, pressedKey, delegateKey, root.currentDevice, root.busy);
        if (activation === null)
            return false;
        root.applySelection({
            index: activation.index,
            key: activation.key,
            rehomed: false
        }, false);
        root.activated(activation.device);
        return true;
    }

    function scrollMouseWheel(angleDeltaY, pixelDeltaY, inverted) {
        var motion = pixelDeltaY !== 0 ? pixelDeltaY : angleDeltaY / 120 * root.rowHeight;
        if (inverted === true)
            motion = -motion;
        var top = deviceList.originY;
        var bottom = Math.max(top, deviceList.originY + deviceList.contentHeight - deviceList.height);
        deviceList.cancelFlick();
        deviceList.contentY = Math.max(top, Math.min(bottom, deviceList.contentY - motion));
    }

    onCandidatesChanged: {
        reconcileHighlighted();
        syncStationaryHover();
    }
    onCurrentDeviceChanged: reconcileHighlighted()
    onBusyChanged: if (!busy)
        reconcileHighlighted()

    ListView {
        id: deviceList

        anchors.fill: parent
        visible: root.candidateCount > 0
        clip: true
        model: root.candidates
        spacing: root.rowSpacing
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        pressDelay: 0
        activeFocusOnTab: true

        onContentYChanged: root.syncStationaryHover()

        WheelHandler {
            target: null
            blocking: true
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: event => {
                root.rememberPointer(Qt.point(event.x, event.y));
                root.scrollMouseWheel(event.angleDelta.y, event.pixelDelta.y, event.inverted);
                root.syncStationaryHover();
                event.accepted = true;
            }
        }

        Accessible.name: root.accessibleName
        Accessible.role: Accessible.List

        Keys.onPressed: event => {
            if (event.key === Qt.Key_Escape) {
                root.dismissRequested();
                event.accepted = true;
            } else if (event.key === Qt.Key_Up) {
                root.highlightAt(Math.max(0, deviceList.currentIndex - 1), true);
                event.accepted = true;
            } else if (event.key === Qt.Key_Down) {
                root.highlightAt(Math.min(root.candidateCount - 1, deviceList.currentIndex + 1), true);
                event.accepted = true;
            } else if (event.key === Qt.Key_Home) {
                if (root.candidateCount > 0)
                    root.highlightAt(0, true);
                event.accepted = true;
            } else if (event.key === Qt.Key_End) {
                if (root.candidateCount > 0)
                    root.highlightAt(root.candidateCount - 1, true);
                event.accepted = true;
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                var index = deviceList.currentIndex;
                if (index >= 0 && index < root.candidateCount) {
                    var candidate = root.candidates[index];
                    root.activateStableKey(root.keyFor(candidate), root.keyFor(candidate));
                }
                event.accepted = true;
            }
        }

        delegate: Item {
            id: deviceRow

            required property var modelData
            required property int index
            property string pressedKey: ""

            readonly property string stableKey: root.keyFor(modelData)
            readonly property bool selected: root.isCurrent(modelData)
            readonly property bool available: modelData.available === true
            readonly property bool canActivate: root.canActivate(modelData)
            readonly property bool keyboardSelected: ListView.isCurrentItem && deviceList.activeFocus
            readonly property bool transientHovered: root.hoveredKey === stableKey
            readonly property bool transientPressed: devicePointer.pressed

            width: ListView.view.width
            height: root.rowHeight
            opacity: available || selected ? 1 : Shell.Theme.disabledOpacity

            onModelDataChanged: pressedKey = ""

            Accessible.name: modelData.label
            Accessible.description: selected ? "Selected audio device" : (available ? "Available audio device; press to select" : "Unavailable audio device")
            Accessible.focusable: true
            Accessible.focused: keyboardSelected
            Accessible.selectable: selected
            Accessible.selected: selected
            Accessible.role: canActivate ? Accessible.Button : Accessible.StaticText
            Accessible.onPressAction: root.activateStableKey(deviceRow.stableKey, deviceRow.stableKey)

            Item {
                id: rowVisual

                anchors.fill: parent
                anchors.margins: root.rowInset

                Components.Surface {
                    anchors.fill: parent
                    interactive: true
                    hovered: deviceRow.transientHovered || deviceRow.keyboardSelected
                    pressed: devicePointer.pressed
                    selected: deviceRow.selected
                    accent: root.accent
                    radius: Shell.Theme.radiusSmall
                    outlineWidth: 0
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: root.horizontalPadding
                    anchors.rightMargin: root.horizontalPadding
                    spacing: Shell.Theme.spacingSmall

                    Rectangle {
                        Layout.preferredWidth: root.markerSize
                        Layout.preferredHeight: root.markerSize
                        radius: Shell.Theme.radiusPill
                        color: deviceRow.available ? (deviceRow.selected ? root.accent : Shell.Theme.secondaryText) : Shell.Theme.error
                    }

                    Text {
                        Layout.fillWidth: true
                        text: deviceRow.modelData.label
                        color: Shell.Theme.primaryText
                        elide: Text.ElideRight
                        font.family: Shell.Theme.sansFont
                        font.pixelSize: Shell.Theme.labelFontSize
                        font.weight: deviceRow.selected ? Font.DemiBold : Font.Normal
                    }

                    Text {
                        visible: root.statusFor(deviceRow.modelData).length > 0
                        text: root.statusFor(deviceRow.modelData)
                        color: deviceRow.available ? (deviceRow.selected ? Shell.Theme.primaryText : Shell.Theme.secondaryText) : Shell.Theme.errorText
                        font.family: Shell.Theme.sansFont
                        font.pixelSize: Shell.Theme.captionFontSize
                        font.weight: deviceRow.selected ? Font.DemiBold : Font.Normal
                    }
                }

                Components.FocusRing {
                    active: deviceRow.keyboardSelected
                    accent: root.accent
                    ringRadius: Shell.Theme.radiusSmall
                }

                MouseArea {
                    id: devicePointer

                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton
                    preventStealing: false
                    scrollGestureEnabled: false
                    cursorShape: deviceRow.canActivate ? Qt.PointingHandCursor : Qt.ArrowCursor

                    function viewportPosition(mouse) {
                        return devicePointer.mapToItem(deviceList, mouse.x, mouse.y);
                    }

                    onEntered: root.rememberPointer(devicePointer.mapToItem(deviceList, devicePointer.mouseX, devicePointer.mouseY))
                    onPositionChanged: mouse => root.rememberPointer(viewportPosition(mouse))
                    onExited: root.forgetPointerFor(deviceRow.stableKey)
                    onPressed: mouse => {
                        root.rememberPointer(viewportPosition(mouse));
                        deviceRow.pressedKey = deviceRow.canActivate ? deviceRow.stableKey : "";
                    }
                    onCanceled: deviceRow.pressedKey = ""
                    onClicked: {
                        var key = deviceRow.pressedKey;
                        deviceRow.pressedKey = "";
                        root.activateStableKey(key, deviceRow.stableKey);
                    }
                }
            }
        }
    }

    Text {
        anchors.centerIn: parent
        width: parent.width - Shell.Theme.spacingMedium * 2
        visible: root.candidateCount === 0
        text: root.emptyText
        color: Shell.Theme.errorText
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        font.family: Shell.Theme.sansFont
        font.pixelSize: Shell.Theme.captionFontSize
    }
}
