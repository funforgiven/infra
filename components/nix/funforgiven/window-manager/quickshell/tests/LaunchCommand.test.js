const assert = require("node:assert/strict");
const test = require("node:test");

const LaunchCommand = require("../services/LaunchCommand.js");

test("desktop entries launch through UWSM as one typed argv", () => {
    const command = LaunchCommand.uwsmAppService("/nix/store/uwsm/bin/uwsm-app", "firefox");

    assert.deepEqual(command, [
        "/nix/store/uwsm/bin/uwsm-app",
        "-t",
        "service",
        "-s",
        "a",
        "-p",
        "KillMode=mixed",
        "--",
        "firefox.desktop"
    ]);
});

test("desktop-entry units require an absolute UWSM launcher", () => {
    assert.throws(
        () => LaunchCommand.uwsmAppService("", "firefox"),
        /launcher is empty/
    );
    assert.throws(
        () => LaunchCommand.uwsmAppService("uwsm-app", "firefox"),
        /must be absolute/
    );
});

test("desktop entry IDs always receive their filename suffix", () => {
    assert.equal(LaunchCommand.desktopEntryId("org.telegram.desktop"), "org.telegram.desktop.desktop");
    assert.equal(LaunchCommand.desktopEntryId(" org.example.App "), "org.example.App.desktop");
    assert.throws(() => LaunchCommand.desktopEntryId("  "), /desktop entry ID is empty/);
});
