import QtQuick
import QtTest
import ".." as Shell
import "../components" as Components
import "../components/IconPolicy.js" as IconPolicy

TestCase {
    name: "ThemeIcons"
    when: windowShown
    width: 160
    height: 80

    function test_symbolicIconUsesSemanticStates() {
        symbolic.enabled = true;
        symbolic.hovered = false;
        symbolic.pressed = false;
        symbolic.active = false;
        compare(symbolic.resolvedColor, Shell.Theme.symbolicIconForeground);
        symbolic.hovered = true;
        compare(symbolic.resolvedColor, Shell.Theme.symbolicIconHover);
        symbolic.pressed = true;
        compare(symbolic.resolvedColor, Shell.Theme.symbolicIconPressed);
        symbolic.active = true;
        compare(symbolic.resolvedColor, Shell.Theme.symbolicIconActive);
        symbolic.enabled = false;
        compare(symbolic.resolvedColor, Shell.Theme.symbolicIconDisabled);
    }

    function test_applicationIconPreservesSourceColors() {
        compare(symbolic.preservesSourceColors, false);
        compare(IconPolicy.preservesSourceColors("application"), true);
    }

    Components.SemanticIcon {
        id: symbolic
        width: 32
        height: 32
    }
}
