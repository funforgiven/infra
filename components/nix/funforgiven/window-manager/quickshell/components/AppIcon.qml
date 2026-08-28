import QtQuick
import Quickshell
import Quickshell.Widgets
import "IconPolicy.js" as IconPolicy

Item {
    id: root

    property string source: Quickshell.iconPath("application-x-executable")
    property string accessibleName: "Application"
    property real iconSize: Math.min(width, height)
    readonly property bool preservesSourceColors: IconPolicy.preservesSourceColors("application")

    Accessible.name: accessibleName
    Accessible.role: Accessible.Graphic

    IconImage {
        anchors.centerIn: parent
        width: Math.min(root.iconSize, root.width)
        height: Math.min(root.iconSize, root.height)
        source: root.source || Quickshell.iconPath("application-x-executable")
        mipmap: true
    }
}
