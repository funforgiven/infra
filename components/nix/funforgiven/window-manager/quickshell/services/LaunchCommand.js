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

function uwsmAppService(launcher, id) {
    var binary = text(launcher);
    if (binary.length === 0) {
        throw new Error("UWSM application launcher is empty");
    }
    if (!binary.startsWith("/")) {
        throw new Error("UWSM application launcher must be absolute");
    }

    return [
        binary,
        "-t",
        "service",
        "-s",
        "a",
        "-p",
        "KillMode=mixed",
        "--",
        desktopEntryId(id)
    ];
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        uwsmAppService: uwsmAppService,
        desktopEntryId: desktopEntryId
    };
}
