import QtQuick
import QtTest
import "../components" as Components

Item {
    id: harness
    width: 400
    height: 200
    property int requests: 0

    Flickable {
        id: viewport
        anchors.fill: parent
        contentWidth: width
        contentHeight: 800
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Components.MaterialSlider {
            id: slider
            x: 20
            y: 60
            width: 360
            value: 50
            minimum: 0
            maximum: 100
            stepSize: 1
            wheelEnabled: false
            onValueRequested: value => {
                harness.requests += 1;
                slider.value = value;
            }
        }
    }

    TestCase {
        name: "SliderWheel"
        when: windowShown

        function init() {
            viewport.cancelFlick();
            viewport.contentY = 0;
            slider.wheelEnabled = false;
            slider.value = 50;
            harness.requests = 0;
            wait(0);
        }

        function test_cameraWheelScrollsWithoutChangingValue() {
            mouseWheel(slider, slider.width / 2, slider.height / 2, 0, -120, Qt.NoButton, Qt.NoModifier, 0);
            compare(harness.requests, 0);
            compare(slider.value, 50);
            tryVerify(() => viewport.contentY > 0);
        }

        function test_cameraHorizontalWheelDoesNotChangeValue() {
            mouseWheel(slider, slider.width / 2, slider.height / 2, 120, 0, Qt.NoButton, Qt.NoModifier, 0);
            compare(harness.requests, 0);
            compare(slider.value, 50);
        }

        function test_explicitClickStillChangesValue() {
            mouseClick(slider, slider.width * 0.75, slider.height / 2, Qt.LeftButton, Qt.NoModifier, 0);
            verify(harness.requests > 0);
            verify(slider.value > 50);
        }

        function test_audioWheelRemainsAvailable() {
            slider.wheelEnabled = true;
            mouseWheel(slider, slider.width / 2, slider.height / 2, 0, 120, Qt.NoButton, Qt.NoModifier, 0);
            compare(harness.requests, 1);
            compare(slider.value, 51);
        }
    }
}
