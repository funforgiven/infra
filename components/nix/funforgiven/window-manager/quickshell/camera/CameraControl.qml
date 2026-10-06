pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import ".." as Shell
import "../components" as Components
import "../services" as Services

ColumnLayout {
    id: root

    required property string controlKey
    required property var control
    readonly property string displayName: ({
            "zoom_absolute": "Zoom",
            "auto_exposure": "Mode",
            "exposure_time_absolute": "Shutter",
            "white_balance_automatic": "Automatic",
            "white_balance_temperature": "Temperature",
            "focus_automatic_continuous": "Autofocus",
            "focus_absolute": "Focus distance",
            "power_line_frequency": "Anti-flicker",
            "backlight_compensation": "Backlight",
            "red_balance": "Red",
            "blue_balance": "Blue"
        })[controlKey] || control.name
    readonly property bool available: control.inactive !== true && control.value !== null

    function valueText(value) {
        if (controlKey === "exposure_time_absolute")
            return (value / 10).toFixed(1) + " ms";
        if (controlKey === "white_balance_temperature")
            return String(value) + " K";
        return String(value);
    }

    function optionLabel(option) {
        if (controlKey === "auto_exposure")
            return ({
                    0: "Auto",
                    1: "Manual",
                    2: "Shutter",
                    3: "Aperture"
                })[option.value] || option.label;
        if (controlKey === "power_line_frequency")
            return ({
                    0: "Off",
                    1: "50 Hz",
                    2: "60 Hz",
                    3: "Auto"
                })[option.value] || option.label;
        return option.label;
    }

    function setValue(value) {
        Services.CameraService.request("set", {
            control: controlKey,
            value: value
        });
    }

    enabled: Services.CameraService.awake && available
    spacing: 0

    CameraToggle {
        Layout.fillWidth: true
        visible: root.control.type === 2
        text: root.displayName
        checked: root.control.value === 1
        onToggled: root.setValue(root.control.value === 1 ? 0 : 1)
    }

    RowLayout {
        Layout.fillWidth: true
        visible: root.control.type !== 2
        spacing: Shell.Theme.spacingSmall
        Text {
            Layout.fillWidth: true
            text: root.displayName
            color: root.enabled ? Shell.Theme.primaryText : Shell.Theme.disabledText
            font.family: Shell.Theme.sansFont
            font.pixelSize: Shell.Theme.labelFontSize
        }
        Text {
            visible: root.control.type === 1
            text: root.control.inactive === true ? "Auto" : root.control.value === null ? "—" : root.valueText(slider.presentedValue)
            color: Shell.Theme.secondaryText
            font.family: Shell.Theme.monoFont
            font.pixelSize: Shell.Theme.captionFontSize
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: root.control.type === 3
        spacing: Shell.Theme.spacingXSmall
        Repeater {
            model: root.control.options || []
            delegate: CameraAction {
                id: optionButton
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                implicitHeight: Shell.Theme.controlCompactSize
                text: root.optionLabel(optionButton.modelData)
                checked: root.control.value === optionButton.modelData.value
                tooltipText: optionButton.modelData.label
                onClicked: root.setValue(optionButton.modelData.value)
            }
        }
    }

    Components.MaterialSlider {
        id: slider
        Layout.fillWidth: true
        implicitHeight: 32
        visible: root.control.type === 1
        value: root.control.value === null ? root.control.default : root.control.value
        minimum: root.control.minimum
        maximum: root.control.maximum
        stepSize: root.control.step
        wheelEnabled: false
        accessibleName: root.displayName
        accessibleValueText: root.valueText(slider.presentedValue)
        onValueRequested: value => root.setValue(Math.round(value))
    }
}
