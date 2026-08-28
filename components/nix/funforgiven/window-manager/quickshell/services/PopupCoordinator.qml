pragma Singleton

import QtQuick
import "PopupOwnership.js" as PopupOwnership

// Ownership policy for interactive top-level shell surfaces:
// - tray, mixer, and launcher are mutually exclusive;
// - modal polkit/idle overlays retire the current owner before appearing;
// - mixer child pickers remain local to their parent surface;
// - input-transparent tooltips do not claim ownership.
// Owners implement their own outside-click, Escape, focus restoration, and
// animation details. Generation tokens make every delayed lifecycle callback
// harmless after replacement, screen migration, or owner destruction.
QtObject {
    id: root

    property var _ownership: PopupOwnership.createState()
    property int _revision: 0

    readonly property string phase: {
        void root._revision;
        return root._ownership.phase;
    }
    readonly property string activeKind: {
        void root._revision;
        return root._ownership.kind;
    }
    readonly property var activeOwner: {
        void root._revision;
        return root._ownership.owner;
    }
    readonly property var activeScreen: {
        void root._revision;
        return root._ownership.screen;
    }
    readonly property int generation: {
        void root._revision;
        return root._ownership.generation;
    }
    readonly property bool inputClaimed: {
        void root._revision;
        return PopupOwnership.inputClaimed(root._ownership);
    }

    signal ownershipChanged

    function _publish() {
        root._revision += 1;
        root.ownershipChanged();
    }

    function open(kind, owner, screen) {
        var transition = PopupOwnership.requestOpen(root._ownership, kind, owner, screen);
        if (!transition.accepted)
            return 0;

        // Publish the new owner before retiring the old one. Any synchronous
        // close callback from the old surface is therefore stale by design.
        root._publish();
        if (transition.previousOwner !== null && typeof transition.previousOwner.closeFromCoordinator === "function")
            transition.previousOwner.closeFromCoordinator(transition.previousToken, "superseded");
        return transition.token;
    }

    function markOpen(owner, token) {
        if (!PopupOwnership.markOpen(root._ownership, owner, token))
            return false;
        root._publish();
        return true;
    }

    function beginClose(owner, token) {
        if (!PopupOwnership.beginClose(root._ownership, owner, token))
            return false;
        root._publish();
        return true;
    }

    function finishClose(owner, token) {
        if (!PopupOwnership.finishClose(root._ownership, owner, token))
            return false;
        root._publish();
        return true;
    }

    function closeActive(reason) {
        var owner = root.activeOwner;
        var token = root.generation;
        if (owner === null)
            return false;
        if (typeof owner.closeFromCoordinator === "function") {
            owner.closeFromCoordinator(token, reason || "dismissed");
            return true;
        }
        root.beginClose(owner, token);
        root.finishClose(owner, token);
        return true;
    }

    function ownerDestroyed(owner) {
        if (!PopupOwnership.forgetOwner(root._ownership, owner))
            return false;
        root._publish();
        return true;
    }

    function isCurrent(owner, token) {
        return PopupOwnership.isCurrent(root._ownership, owner, token);
    }
}
