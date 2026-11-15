function text(value) {
    if (value === undefined || value === null) {
        return "";
    }
    return String(value).trim();
}

function appendUnique(target, value) {
    value = text(value);
    if (value.length === 0) {
        return;
    }

    var lowered = value.toLowerCase();
    for (var index = 0; index < target.length; index += 1) {
        if (target[index].toLowerCase() === lowered) {
            return;
        }
    }
    target.push(value);
}

function primaryCandidates(hints) {
    hints = hints && typeof hints === "object" ? hints : {};

    var values = [];
    appendUnique(values, hints.appId);
    appendUnique(values, hints.applicationId);
    return values;
}

function fallbackCandidates(hints) {
    hints = hints && typeof hints === "object" ? hints : {};

    var values = [];
    appendUnique(values, hints.applicationName);
    appendUnique(values, hints.processBinary);
    return values;
}

function candidates(hints) {
    var values = primaryCandidates(hints);
    var fallback = fallbackCandidates(hints);

    for (var index = 0; index < fallback.length; index += 1) {
        appendUnique(values, fallback[index]);
    }
    return values;
}

function aliasFor(values, aliases) {
    aliases = aliases && typeof aliases === "object" ? aliases : {};
    var keys = Object.keys(aliases);
    var valueIndex;
    var keyIndex;

    for (valueIndex = 0; valueIndex < values.length; valueIndex += 1) {
        if (Object.prototype.hasOwnProperty.call(aliases, values[valueIndex])) {
            return {
                source: values[valueIndex],
                target: text(aliases[values[valueIndex]])
            };
        }
    }

    for (valueIndex = 0; valueIndex < values.length; valueIndex += 1) {
        var lowered = values[valueIndex].toLowerCase();
        for (keyIndex = 0; keyIndex < keys.length; keyIndex += 1) {
            if (keys[keyIndex].toLowerCase() === lowered) {
                return {
                    source: values[valueIndex],
                    target: text(aliases[keys[keyIndex]])
                };
            }
        }
    }

    return null;
}

function fallbackId(values) {
    if (!values || values.length === 0) {
        return "unknown-application";
    }
    return values[0].toLowerCase();
}

function niriWindowFallbackId(windowId) {
    windowId = text(windowId);
    return windowId.length === 0 ? "" : "niri-window:" + windowId;
}

function windowCanonicalId(resolution, appId, windowId) {
    resolution = resolution && typeof resolution === "object" ? resolution : {};
    var existing = text(resolution.canonicalId);
    if (text(appId).length > 0
            || (resolution.desktopEntry !== null && resolution.desktopEntry !== undefined)) {
        return existing;
    }
    return niriWindowFallbackId(windowId) || existing;
}

function executableName(command) {
    if (!command || typeof command.length !== "number" || command.length === 0) {
        return "";
    }
    var executable = text(command[0]);
    var separator = executable.lastIndexOf("/");
    return separator === -1 ? executable : executable.slice(separator + 1);
}

function directIconSource(value) {
    value = text(value);
    if (value.startsWith("/") || /^[A-Za-z][A-Za-z0-9+.-]*:/.test(value)) {
        return value;
    }
    return "";
}

// Icon substitution and lookup order follow DankMaterialShell's Paths.qml and
// DesktopService.qml (MIT, see THIRD_PARTY_NOTICES.md).
var steamIconSubstitution = {
    type: "regex",
    pattern: "^steam_app_(\\d+)$",
    replacement: "steam_icon_$1"
};

function substituteIcon(appId, substitutions) {
    appId = text(appId);
    if (appId.length === 0) {
        return "";
    }

    var rules = (substitutions || []).concat([steamIconSubstitution]);
    for (var index = 0; index < rules.length; index += 1) {
        var rule = rules[index] || {};
        var pattern = text(rule.pattern);
        var replacement = text(rule.replacement);
        if (pattern.length === 0 || replacement.length === 0) {
            continue;
        }
        if (rule.type === "exact" && appId === pattern) {
            return replacement;
        }
        if (rule.type === "contains" && appId.indexOf(pattern) !== -1) {
            return replacement;
        }
        if (rule.type === "regex") {
            var match = appId.match(new RegExp(pattern));
            if (match) {
                return replacement.replace(/\$(\d+)/g, function (_, group) {
                    return match[group] || "";
                });
            }
        }
    }
    return "";
}

// Icon themes are case-sensitive, so unlike appendUnique this keeps case variants.
function iconNameCandidates(names) {
    var values = [];
    function add(value) {
        value = text(value);
        if (value.length > 0 && values.indexOf(value) === -1) {
            values.push(value);
        }
    }

    for (var index = 0; index < (names || []).length; index += 1) {
        var name = text(names[index]);
        if (directIconSource(name)) {
            continue;
        }
        var lastPart = name.split(".").pop();
        add(name);
        add(name.toLowerCase());
        if (lastPart !== name) {
            add(lastPart);
            add(lastPart.toLowerCase());
        }
    }
    return values;
}

function entryMentions(entry, appId) {
    var needle = text(appId).replace(/-bin$/, "").toLowerCase();
    if (!entry || needle.length < 3) {
        return false;
    }
    var command = entry.command && typeof entry.command.join === "function" ? entry.command.join(" ") : "";
    return text(entry.id).toLowerCase().indexOf(needle) !== -1
        || text(entry.name).toLowerCase().indexOf(needle) !== -1
        || text(entry.execString || command).toLowerCase().indexOf(needle) !== -1;
}

function entryMatchesName(entry, candidate) {
    candidate = text(candidate).toLowerCase();
    if (!entry || candidate.length === 0) {
        return false;
    }
    return text(entry.name).toLowerCase() === candidate
        || text(entry.genericName).toLowerCase() === candidate;
}

function entryMatchesExecutable(entry, candidate) {
    candidate = text(candidate).toLowerCase();
    if (!entry || candidate.length === 0) {
        return false;
    }
    var executable = executableName(entry.command).toLowerCase();
    return executable === candidate || text(entry.command && entry.command[0]).toLowerCase() === candidate;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        aliasFor: aliasFor,
        candidates: candidates,
        directIconSource: directIconSource,
        entryMatchesExecutable: entryMatchesExecutable,
        entryMatchesName: entryMatchesName,
        entryMentions: entryMentions,
        executableName: executableName,
        fallbackCandidates: fallbackCandidates,
        fallbackId: fallbackId,
        iconNameCandidates: iconNameCandidates,
        niriWindowFallbackId: niriWindowFallbackId,
        primaryCandidates: primaryCandidates,
        substituteIcon: substituteIcon,
        text: text,
        windowCanonicalId: windowCanonicalId
    };
}
