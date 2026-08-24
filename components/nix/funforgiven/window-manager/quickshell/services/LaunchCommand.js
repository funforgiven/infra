function text(value) {
    if (value === null || value === undefined) {
        return "";
    }
    return String(value).trim();
}

function desktopEntryId(value) {
    var id = text(value);
    if (id.length === 0) {
        throw new Error("desktop entry ID is empty");
    }
    // Quickshell exposes the desktop-entry ID, which is the filename with only
    // its final ".desktop" suffix removed. Some valid IDs, notably Telegram's
    // "org.telegram.desktop", therefore still end in ".desktop".
    return id + ".desktop";
}

function app2unitService(launcher, id, applicationStopTimeout) {
    var stopTimeout = text(applicationStopTimeout);
    if (!/^[1-9][0-9]*s$/.test(stopTimeout)) {
        throw new Error("application stop timeout must be a positive whole number of seconds");
    }

    return [
        text(launcher),
        "-t",
        "service",
        "-s",
        "app-graphical.slice",
        "-p",
        "TimeoutStopSec=" + stopTimeout,
        "-p",
        "KillMode=mixed",
        "-p",
        "KillSignal=SIGTERM",
        "-p",
        "SendSIGKILL=yes",
        "--",
        desktopEntryId(id)
    ];
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        app2unitService: app2unitService,
        desktopEntryId: desktopEntryId
    };
}
