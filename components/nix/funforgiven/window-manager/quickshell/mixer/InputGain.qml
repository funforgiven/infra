import QtQuick
import QtQuick.Layouts
import ".." as Shell
import "../components" as Components
import "../services" as Services

ColumnLayout {
    id: root

    required property var input
    required property color accent
    readonly property var inputAudio: input && input.node ? input.node.audio : null
    readonly property real value: inputAudio ? Math.max(0, Math.min(1, Number(inputAudio.volume))) : 0
    readonly property bool available: inputAudio !== null

    spacing: Shell.Theme.spacingXSmall

    RowLayout {
        Layout.fillWidth: true

        Item {
            Layout.fillWidth: true
        }

        Text {
            text: root.available ? Math.round(gainSlider.presentedValue * 100) + "%" : "Unavailable"
            color: root.available ? Shell.Theme.primaryText : Shell.Theme.errorText
            font.family: Shell.Theme.monoFont
            font.pixelSize: Shell.Theme.labelFontSize
            font.weight: Font.DemiBold
        }
    }

    Components.MaterialSlider {
        id: gainSlider

        Layout.fillWidth: true
        value: root.value
        accent: root.accent
        enabled: root.available
        accessibleName: "Microphone volume"
        onValueRequested: value => {
            if (root.input)
                Services.AudioActions.setInputVolume(root.input.id, root.input.serial, value);
        }
    }
}
