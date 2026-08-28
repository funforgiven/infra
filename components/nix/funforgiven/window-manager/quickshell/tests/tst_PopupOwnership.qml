import QtQuick
import QtTest
import "../bar/TrayMenuState.js" as TrayMenuState
import "../services/PopupOwnership.js" as PopupOwnership

TestCase {
    name: "PopupOwnershipQml"

    property QtObject steamMenu: QtObject {}
    property QtObject discordMenu: QtObject {}
    property QtObject networkMenu: QtObject {}
    property QtObject steam: QtObject {
        property var menu: steamMenu
    }
    property QtObject discord: QtObject {
        property var menu: discordMenu
    }
    property QtObject network: QtObject {
        property var menu: networkMenu
    }
    property QtObject steamAnchor: QtObject {}
    property QtObject discordAnchor: QtObject {}
    property QtObject networkAnchor: QtObject {}

    function test_firstClickSwitchesAndStaleCloseIsIgnored() {
        var state = TrayMenuState.createState();
        var first = TrayMenuState.requestOpen(state, steam, steam.menu, steamAnchor);
        verify(TrayMenuState.markOpen(state, first.token));
        var staleClose = TrayMenuState.beginClose(state);

        var replacement = TrayMenuState.requestOpen(state, discord, discord.menu, discordAnchor);
        compare(replacement.action, "open");
        compare(state.item, discord);
        verify(!TrayMenuState.finishClose(state, staleClose));
        verify(TrayMenuState.markOpen(state, replacement.token));
        compare(state.phase, "open");
    }

    function test_twentyAlternatingMenuHandles() {
        var state = TrayMenuState.createState();
        var items = [steam, discord, network];
        var anchors = [steamAnchor, discordAnchor, networkAnchor];
        for (var index = 0; index < 20; index += 1) {
            var itemIndex = index % items.length;
            var item = items[itemIndex];
            var transition = TrayMenuState.requestOpen(state, item, item.menu, anchors[itemIndex]);
            verify(transition.action === "open" || transition.action === "switch");
            compare(state.item, item);
            verify(TrayMenuState.markOpen(state, transition.token));
        }
        compare(state.generation, 20);
    }

    function test_toggleAndDismissReleaseInput() {
        var state = TrayMenuState.createState();
        var opened = TrayMenuState.requestOpen(state, steam, steam.menu, steamAnchor);
        verify(TrayMenuState.markOpen(state, opened.token));
        compare(TrayMenuState.requestOpen(state, steam, steam.menu, steamAnchor).action, "close");
        var closeToken = TrayMenuState.beginClose(state);
        verify(!TrayMenuState.inputClaimed(state));
        verify(TrayMenuState.finishClose(state, closeToken));
        compare(state.item, null);
    }

    function test_popupReplacementRejectsOldOwnerCompletion() {
        var state = PopupOwnership.createState();
        var trayOwner = Qt.createQmlObject("import QtQuick; QtObject {}", this);
        var mixerOwner = Qt.createQmlObject("import QtQuick; QtObject {}", this);
        var trayOpen = PopupOwnership.requestOpen(state, "tray-menu", trayOwner, "DP-1");
        verify(PopupOwnership.markOpen(state, trayOwner, trayOpen.token));
        var mixerOpen = PopupOwnership.requestOpen(state, "mixer", mixerOwner, "DP-1");
        compare(mixerOpen.previousOwner, trayOwner);
        verify(!PopupOwnership.finishClose(state, trayOwner, trayOpen.token));
        verify(PopupOwnership.markOpen(state, mixerOwner, mixerOpen.token));
        compare(state.owner, mixerOwner);
        trayOwner.destroy();
        mixerOwner.destroy();
    }

    function test_screenMoveInvalidatesOldSurfaceToken() {
        var state = PopupOwnership.createState();
        var owner = Qt.createQmlObject("import QtQuick; QtObject {}", this);
        var first = PopupOwnership.requestOpen(state, "tray-menu", owner, "DP-1");
        verify(PopupOwnership.markOpen(state, owner, first.token));
        var moved = PopupOwnership.requestOpen(state, "tray-menu", owner, "HDMI-A-1");
        compare(state.screen, "HDMI-A-1");
        verify(!PopupOwnership.finishClose(state, owner, first.token));
        verify(PopupOwnership.markOpen(state, owner, moved.token));
        verify(PopupOwnership.inputClaimed(state));
        verify(PopupOwnership.beginClose(state, owner, moved.token));
        verify(!PopupOwnership.inputClaimed(state));
        verify(PopupOwnership.finishClose(state, owner, moved.token));
        owner.destroy();
    }
}
