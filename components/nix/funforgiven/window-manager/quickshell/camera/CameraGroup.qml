pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import ".." as Shell
import "../components" as Components

Components.Surface {
    id: root

    property string title: ""
    property string icon: ""
    default property alias contents: content.data

    implicitWidth: 240
    implicitHeight: content.implicitHeight + Shell.Theme.spacingLarge * 2
    outlineWidth: 0
    radius: Shell.Theme.radiusMedium

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: Shell.Theme.spacingLarge
        spacing: Shell.Theme.spacingSmall

        RowLayout {
            Layout.fillWidth: true
            spacing: Shell.Theme.spacingSmall
            Components.SemanticIcon {
                source: root.icon.length > 0 ? Qt.resolvedUrl("icons/" + root.icon + ".svg") : ""
                Layout.preferredWidth: Shell.Theme.iconSmallSize
                Layout.preferredHeight: Shell.Theme.iconSmallSize
                muted: true
            }
            Text {
                Layout.fillWidth: true
                text: root.title
                color: Shell.Theme.secondaryText
                font.family: Shell.Theme.sansFont
                font.pixelSize: Shell.Theme.labelFontSize
                font.weight: Font.DemiBold
            }
        }
    }
}
