import QtQuick
import ".." as Shell
import "IconPolicy.js" as IconPolicy

Item {
    id: root

    property url source
    property bool hovered: false
    property bool pressed: false
    property bool active: false
    property bool selected: false
    property bool checked: false
    property bool attention: false
    property bool warning: false
    property bool destructive: false
    property bool muted: false

    readonly property bool preservesSourceColors: IconPolicy.preservesSourceColors("symbolic")
    readonly property color resolvedColor: IconPolicy.resolve(Shell.Theme, {
        enabled: root.enabled,
        hovered: root.hovered,
        pressed: root.pressed,
        active: root.active,
        selected: root.selected,
        checked: root.checked,
        attention: root.attention,
        warning: root.warning,
        destructive: root.destructive,
        muted: root.muted
    })

    TintedIcon {
        anchors.fill: parent
        source: root.source
        tint: root.resolvedColor
    }
}
