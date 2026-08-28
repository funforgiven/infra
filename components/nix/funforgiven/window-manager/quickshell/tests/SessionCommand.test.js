const assert = require("node:assert/strict");
const test = require("node:test");

const SessionCommand = require("../services/SessionCommand.js");

test("session actions use UWSM for logout and systemd for machine actions", () => {
    const uwsm = "/nix/store/uwsm/bin/uwsm";
    const systemctl = "/nix/store/systemd/bin/systemctl";

    assert.deepEqual(SessionCommand.sessionAction(uwsm, systemctl, "logout"), [uwsm, "stop"]);
    assert.deepEqual(SessionCommand.sessionAction(uwsm, systemctl, "reboot"), [systemctl, "reboot"]);
    assert.deepEqual(SessionCommand.sessionAction(uwsm, systemctl, "poweroff"), [systemctl, "poweroff"]);
});

test("session actions reject empty executables and arbitrary verbs", () => {
    assert.throws(() => SessionCommand.sessionAction("/bin/uwsm", "", "reboot"), /systemctl executable is empty/);
    assert.throws(() => SessionCommand.sessionAction("uwsm", "/bin/systemctl", "logout"), /UWSM executable must be absolute/);
    assert.throws(() => SessionCommand.sessionAction("/bin/uwsm", "/bin/systemctl", "suspend"), /unsupported system action/);
    assert.throws(() => SessionCommand.sessionAction("/bin/uwsm", "/bin/systemctl", "--force"), /unsupported system action/);
});
