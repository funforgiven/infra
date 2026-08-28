const assert = require("node:assert/strict");
const test = require("node:test");

const PopupOwnership = require("../services/PopupOwnership.js");
const TrayMenuState = require("../bar/TrayMenuState.js");

function trayItem(name) {
    return { name, menu: { name: `${name}-menu` } };
}

test("one right-click switches the authoritative tray item", () => {
    const state = TrayMenuState.createState();
    const steam = trayItem("steam");
    const discord = trayItem("discord");

    let transition = TrayMenuState.requestOpen(state, steam, steam.menu, { name: "steam-anchor" });
    assert.equal(transition.action, "open");
    assert.equal(TrayMenuState.markOpen(state, transition.token), true);

    transition = TrayMenuState.requestOpen(state, discord, discord.menu, { name: "discord-anchor" });
    assert.equal(transition.action, "switch");
    assert.equal(state.item, discord);
    assert.equal(state.menu, discord.menu);
    assert.equal(TrayMenuState.inputClaimed(state), true);
    assert.equal(TrayMenuState.markOpen(state, transition.token), true);
    assert.equal(state.phase, "open");
});

test("twenty rapid tray switches produce twenty authoritative transitions", () => {
    const state = TrayMenuState.createState();
    const items = [trayItem("steam"), trayItem("discord"), trayItem("network")];

    for (let index = 0; index < 20; index += 1) {
        const item = items[index % items.length];
        const transition = TrayMenuState.requestOpen(state, item, item.menu, { name: `${item.name}-${index}` });
        assert.notEqual(transition.action, "reject");
        assert.notEqual(transition.action, "close");
        assert.equal(state.item, item);
        assert.equal(TrayMenuState.markOpen(state, transition.token), true);
    }
    assert.equal(state.generation, 20);
});

test("right-clicking the open tray item toggles it closed and releases input", () => {
    const state = TrayMenuState.createState();
    const steam = trayItem("steam");
    const opened = TrayMenuState.requestOpen(state, steam, steam.menu, {});
    TrayMenuState.markOpen(state, opened.token);

    assert.equal(TrayMenuState.requestOpen(state, steam, steam.menu, {}).action, "close");
    const closingToken = TrayMenuState.beginClose(state);
    assert.equal(TrayMenuState.inputClaimed(state), false);
    assert.equal(TrayMenuState.finishClose(state, closingToken), true);
    assert.equal(state.phase, "closed");
    assert.equal(state.item, null);
});

test("a stale tray close completion cannot close a replacement menu", () => {
    const state = TrayMenuState.createState();
    const steam = trayItem("steam");
    const discord = trayItem("discord");

    const first = TrayMenuState.requestOpen(state, steam, steam.menu, {});
    TrayMenuState.markOpen(state, first.token);
    const staleClosingToken = TrayMenuState.beginClose(state);
    const replacement = TrayMenuState.requestOpen(state, discord, discord.menu, {});

    assert.equal(TrayMenuState.finishClose(state, staleClosingToken), false);
    assert.equal(state.item, discord);
    assert.equal(TrayMenuState.markOpen(state, replacement.token), true);
});

test("outside click, Escape, menu destruction, item removal, and anchor destruction share close semantics", () => {
    for (const reason of ["outside", "escape", "menu-destroyed", "removed", "anchor-destroyed"]) {
        const state = TrayMenuState.createState();
        const item = trayItem(reason);
        const anchor = { name: reason };
        const opened = TrayMenuState.requestOpen(state, item, item.menu, anchor);
        TrayMenuState.markOpen(state, opened.token);
        assert.equal(TrayMenuState.ownsItem(state, item), true);
        assert.equal(TrayMenuState.ownsAnchor(state, anchor), true);
        const closeToken = TrayMenuState.beginClose(state);
        assert.equal(TrayMenuState.inputClaimed(state), false);
        assert.equal(TrayMenuState.finishClose(state, closeToken), true);
    }
});

test("a stale popup owner callback cannot clear its replacement", () => {
    const state = PopupOwnership.createState();
    const tray = { name: "tray" };
    const mixer = { name: "mixer" };

    const trayOpen = PopupOwnership.requestOpen(state, "tray-menu", tray, "DP-1");
    PopupOwnership.markOpen(state, tray, trayOpen.token);
    const mixerOpen = PopupOwnership.requestOpen(state, "mixer", mixer, "DP-1");

    assert.equal(mixerOpen.previousOwner, tray);
    assert.equal(PopupOwnership.finishClose(state, tray, trayOpen.token), false);
    assert.equal(PopupOwnership.markOpen(state, mixer, mixerOpen.token), true);
    assert.equal(state.owner, mixer);
    assert.equal(state.kind, "mixer");
});

test("moving one popup owner to a new screen invalidates the old surface token", () => {
    const state = PopupOwnership.createState();
    const tray = { name: "tray" };

    const first = PopupOwnership.requestOpen(state, "tray-menu", tray, "DP-1");
    PopupOwnership.markOpen(state, tray, first.token);
    const moved = PopupOwnership.requestOpen(state, "tray-menu", tray, "HDMI-A-1");

    assert.equal(moved.previousOwner, null);
    assert.equal(state.screen, "HDMI-A-1");
    assert.equal(PopupOwnership.finishClose(state, tray, first.token), false);
    assert.equal(PopupOwnership.markOpen(state, tray, moved.token), true);
    assert.equal(PopupOwnership.inputClaimed(state), true);

    assert.equal(PopupOwnership.beginClose(state, tray, moved.token), true);
    assert.equal(PopupOwnership.inputClaimed(state), false);
    assert.equal(PopupOwnership.finishClose(state, tray, moved.token), true);
});
