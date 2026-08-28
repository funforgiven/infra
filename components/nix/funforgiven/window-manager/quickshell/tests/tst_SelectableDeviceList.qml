import QtQuick
import QtTest
import "../mixer" as Mixer

Item {
    id: harness

    width: 800
    height: 420

    property var outputCandidates: []
    property var microphoneCandidates: []
    property var outputActivations: []
    property var microphoneActivations: []

    TestCase {
        id: testCase

        name: "SelectableDeviceList"
        when: windowShown

        function devices(prefix) {
            var result = [];
            for (var index = 0; index < 8; index += 1) {
                result.push({
                    id: prefix + index,
                    serial: 1000 + index,
                    label: prefix + " device " + index,
                    available: true
                });
            }
            return result;
        }

        function resetLists() {
            harness.outputCandidates = devices("output-");
            harness.microphoneCandidates = devices("input-");
            harness.outputActivations = [];
            harness.microphoneActivations = [];
            outputList.busy = false;
            microphoneList.busy = false;
            outputList.view.contentY = 0;
            microphoneList.view.contentY = 0;
            wait(0);
            outputList.focusInitial();
            microphoneList.focusInitial();
        }

        function init() {
            resetLists();
        }

        function clickVisibleRowImmediatelyAfterWheel(list) {
            var pointerX = list.width / 2;
            var pointerY = list.height / 2;
            var before = list.view.contentY;
            var beforeIndex = list.view.indexAt(pointerX, before + pointerY);
            verify(beforeIndex >= 0);
            var beforeRow = list.view.itemAtIndex(beforeIndex);
            verify(beforeRow !== null);
            mouseWheel(list, pointerX, pointerY, 0, -120, Qt.NoButton, Qt.NoModifier, 0);
            verify(list.view.contentY > before);
            var contentY = list.view.contentY + pointerY;
            var index = list.view.indexAt(pointerX, contentY);
            verify(index >= 0);
            verify(index !== beforeIndex);
            var row = list.view.itemAtIndex(index);
            verify(row !== null);
            compare(row.canActivate, true);
            compare(row.transientHovered, true);
            compare(beforeRow.transientHovered, false);
            // Keep the pointer at the wheel event's exact window coordinate.
            // Targeting the moved delegate itself would synthesize a pointer
            // move and hide stale hit-testing/handler-grab regressions.
            mousePress(list, pointerX, pointerY, Qt.LeftButton, Qt.NoModifier, 0);
            compare(row.pressedKey, row.stableKey);
            compare(row.transientPressed, true);
            mouseRelease(list, pointerX, pointerY, Qt.LeftButton, Qt.NoModifier, 0);
            var activations = list === outputList ? harness.outputActivations : harness.microphoneActivations;
            compare(activations.length, 1);
            compare(activations[0].id, list.candidates[index].id);
        }

        function test_outputSingleClickImmediatelyAfterWheel() {
            clickVisibleRowImmediatelyAfterWheel(outputList);
        }

        function test_microphoneSingleClickImmediatelyAfterWheel() {
            clickVisibleRowImmediatelyAfterWheel(microphoneList);
        }

        function test_dragDoesNotActivate() {
            var row = outputList.view.itemAtIndex(1);
            verify(row !== null);
            mouseDrag(row, row.width / 2, row.height / 2, 0, 48, Qt.LeftButton, Qt.NoModifier, 0);
            compare(harness.outputActivations.length, 0);
        }

        function test_plainDelegateClickActivates() {
            var row = outputList.view.itemAtIndex(1);
            verify(row !== null);
            compare(row.canActivate, true);
            mouseClick(row, row.width / 2, row.height / 2, Qt.LeftButton, Qt.NoModifier, 0);
            compare(harness.outputActivations.length, 1);
            compare(harness.outputActivations[0].id, harness.outputCandidates[1].id);
        }

        function test_modelChangeBetweenPressAndReleaseCannotSelectWrongDevice() {
            var row = outputList.view.itemAtIndex(1);
            var removedId = row.modelData.id;
            mousePress(row, row.width / 2, row.height / 2, Qt.LeftButton, Qt.NoModifier, 0);
            harness.outputCandidates = harness.outputCandidates.filter(function (candidate) {
                return candidate.id !== removedId;
            });
            wait(0);
            mouseRelease(outputList, outputList.width / 2, outputList.height / 2, Qt.LeftButton, Qt.NoModifier, 0);
            compare(harness.outputActivations.length, 0);
        }

        function test_recycledDelegateHasDerivedTransientState() {
            var oldRow = outputList.view.itemAtIndex(0);
            verify(oldRow !== null);
            compare(oldRow.transientPressed, false);
            outputList.view.positionViewAtEnd();
            wait(0);
            var newRow = outputList.view.itemAtIndex(harness.outputCandidates.length - 1);
            verify(newRow !== null);
            compare(newRow.pressedKey, "");
            compare(newRow.transientPressed, false);
            compare(newRow.selected, false);
            outputList.busy = true;
            compare(newRow.canActivate, false);
            outputList.busy = false;
        }

        function test_keyboardSelectionActivatesExactlyOnce() {
            outputList.focusInitial();
            keyClick(Qt.Key_Down);
            keyClick(Qt.Key_Return);
            compare(harness.outputActivations.length, 1);
            compare(harness.outputActivations[0].id, harness.outputCandidates[1].id);
        }
    }

    Mixer.SelectableDeviceList {
        id: outputList

        x: 20
        y: 20
        width: 360
        height: 180
        candidates: harness.outputCandidates
        currentDevice: harness.outputCandidates.length > 0 ? harness.outputCandidates[0] : null
        accessibleName: "Fake outputs"
        onActivated: device => harness.outputActivations = harness.outputActivations.concat([device])
    }

    Mixer.SelectableDeviceList {
        id: microphoneList

        x: 420
        y: 20
        width: 360
        height: 180
        candidates: harness.microphoneCandidates
        currentDevice: harness.microphoneCandidates.length > 0 ? harness.microphoneCandidates[0] : null
        accessibleName: "Fake microphones"
        onActivated: device => harness.microphoneActivations = harness.microphoneActivations.concat([device])
    }
}
