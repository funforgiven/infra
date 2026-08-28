function text(value) {
    if (value === null || value === undefined) {
        return "";
    }
    return String(value).trim();
}

function absoluteExecutable(value, label) {
    var binary = text(value);
    if (binary.length === 0) {
        throw new Error(label + " executable is empty");
    }
    if (!binary.startsWith("/")) {
        throw new Error(label + " executable must be absolute");
    }
    return binary;
}

function sessionAction(uwsmExecutable, systemctlExecutable, action) {
    if (action !== "logout" && action !== "reboot" && action !== "poweroff") {
        throw new Error("unsupported system action: " + text(action));
    }

    if (action === "logout") {
        return [absoluteExecutable(uwsmExecutable, "UWSM"), "stop"];
    }

    return [absoluteExecutable(systemctlExecutable, "systemctl"), action];
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        sessionAction: sessionAction
    };
}
