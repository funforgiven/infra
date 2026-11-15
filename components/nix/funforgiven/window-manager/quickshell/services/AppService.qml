pragma Singleton
pragma ComponentBehavior: Bound

import QtQml
import Quickshell
import Quickshell.Io
import ".." as Shell
import "AppIdentity.js" as AppIdentity
import "LaunchCommand.js" as LaunchCommand

QtObject {
    id: root

    readonly property string fallbackIcon: "application-x-executable"
    property int revision: 0
    property int launchStateRevision: 0
    property var pendingDesktopIds: []
    property var _pendingLaunchCounts: ({})
    readonly property var _identityCacheStore: ({
            revision: -1,
            size: 0,
            entries: null
        })
    property string lastLaunchFailureDesktopId: ""
    property string lastLaunchFailureMessage: ""

    signal launchRequested(string desktopId)
    signal launchSucceeded(string desktopId)
    signal launchFailed(string desktopId, string message)

    function _value(object, names) {
        if (object === null || object === undefined) {
            return "";
        }

        for (let index = 0; index < names.length; index += 1) {
            let value = object[names[index]];
            if (value !== undefined && value !== null && String(value).trim().length > 0) {
                return String(value).trim();
            }
        }
        return "";
    }

    function _streamValue(stream, names) {
        if (stream === null || stream === undefined) {
            return "";
        }

        var properties = stream.properties;
        var propertyValue = root._value(properties, names);
        return propertyValue || root._value(stream, names);
    }

    function _entryById(id) {
        if (id.length === 0) {
            return null;
        }
        return DesktopEntries.byId(id);
    }

    function _firstExact(values) {
        for (let index = 0; index < values.length; index += 1) {
            let entry = root._entryById(values[index]);
            if (entry !== null) {
                return entry;
            }
        }
        return null;
    }

    function _firstHeuristic(values) {
        for (let index = 0; index < values.length; index += 1) {
            let entry = DesktopEntries.heuristicLookup(values[index]);
            if (entry !== null) {
                return entry;
            }
        }
        return null;
    }

    function _applications() {
        var model = DesktopEntries.applications;
        return model && model.values ? model.values : [];
    }

    function _textList(value) {
        if (value === null || value === undefined) {
            return [];
        }

        var values = typeof value === "string" ? value.split(";") : value;
        var result = [];
        for (let index = 0; index < values.length; index += 1) {
            let item = AppIdentity.text(values[index]);
            if (item.length > 0) {
                result.push(item);
            }
        }
        return result;
    }

    function _themedIcon(names) {
        var candidates = AppIdentity.iconNameCandidates(names);
        for (let index = 0; index < candidates.length; index += 1) {
            let path = Quickshell.iconPath(candidates[index], true);
            if (path) {
                return path;
            }
        }
        return "";
    }

    // Try the substitution, then the declared icons, then the app ID as an icon
    // name, then any desktop entry that mentions the app ID.
    function _iconPath(iconNames, appId) {
        var substitute = AppIdentity.substituteIcon(appId, Shell.ShellConfig.iconSubstitutions);
        var direct = AppIdentity.directIconSource(substitute);
        if (direct) {
            return direct;
        }

        for (let index = 0; index < iconNames.length; index += 1) {
            direct = AppIdentity.directIconSource(iconNames[index]);
            if (direct) {
                return direct;
            }
        }

        var path = root._themedIcon([substitute]) || root._themedIcon(iconNames) || root._themedIcon([appId]);
        if (path) {
            return path;
        }

        var entry = root._firstModelMatch(appId, AppIdentity.entryMentions);
        path = entry === null ? "" : root._themedIcon([entry.icon]);
        return path || Quickshell.iconPath(root.fallbackIcon);
    }

    function launcherApplications(revision) {
        void revision;

        var entries = root._applications();
        var applications = [];
        var seen = Object.create(null);
        for (let index = 0; index < entries.length; index += 1) {
            let entry = entries[index];
            let desktopId = AppIdentity.text(entry.id);
            if (desktopId.length === 0 || seen[desktopId] || entry.noDisplay === true || entry.hidden === true || !entry.command || entry.command.length === 0) {
                continue;
            }
            seen[desktopId] = true;

            applications.push({
                id: desktopId,
                name: AppIdentity.text(entry.name) || desktopId,
                genericName: root._value(entry, ["genericName", "generic_name"]),
                comment: root._value(entry, ["comment"]),
                keywords: root._textList(entry.keywords),
                iconPath: root._iconPath([AppIdentity.text(entry.icon)], desktopId)
            });
        }
        return applications;
    }

    function _copyLaunchCounts() {
        var copy = Object.create(null);
        var ids = Object.keys(root._pendingLaunchCounts);
        for (let index = 0; index < ids.length; index += 1) {
            copy[ids[index]] = root._pendingLaunchCounts[ids[index]];
        }
        return copy;
    }

    function _publishPending(counts) {
        root._pendingLaunchCounts = counts;
        root.pendingDesktopIds = Object.keys(counts).filter(function (desktopId) {
            return counts[desktopId] > 0;
        }).sort();
        root.launchStateRevision += 1;
    }

    function _beginLaunch(process) {
        if (!process || process.pendingRegistered) {
            return;
        }

        var counts = root._copyLaunchCounts();
        counts[process.desktopId] = (counts[process.desktopId] || 0) + 1;
        process.pendingRegistered = true;
        root._publishPending(counts);
    }

    function _endLaunch(process) {
        if (!process || !process.pendingRegistered) {
            return;
        }

        var counts = root._copyLaunchCounts();
        var remaining = (counts[process.desktopId] || 1) - 1;
        if (remaining > 0) {
            counts[process.desktopId] = remaining;
        } else {
            delete counts[process.desktopId];
        }
        process.pendingRegistered = false;
        root._publishPending(counts);
    }

    function isLaunchPending(desktopId) {
        var revision = root.launchStateRevision;
        void revision;
        var normalized = AppIdentity.text(desktopId);
        return normalized.length > 0 && (root._pendingLaunchCounts[normalized] || 0) > 0;
    }

    function clearLaunchFailure(desktopId) {
        var normalized = AppIdentity.text(desktopId);
        if (root.lastLaunchFailureMessage.length === 0 || (normalized.length > 0 && normalized !== root.lastLaunchFailureDesktopId)) {
            return;
        }
        root.lastLaunchFailureDesktopId = "";
        root.lastLaunchFailureMessage = "";
        root.launchStateRevision += 1;
    }

    function _reportLaunchFailure(desktopId, message) {
        root.lastLaunchFailureDesktopId = AppIdentity.text(desktopId);
        root.lastLaunchFailureMessage = AppIdentity.text(message) || "application launch failed";
        root.launchStateRevision += 1;
        root.launchFailed(root.lastLaunchFailureDesktopId, root.lastLaunchFailureMessage);
    }

    function _reportLaunchSuccess(desktopId) {
        root.clearLaunchFailure(desktopId);
        root.launchSucceeded(desktopId);
    }

    function _firstModelMatch(value, matcher) {
        var entries = root._applications();
        for (let index = 0; index < entries.length; index += 1) {
            if (matcher(entries[index], value)) {
                return entries[index];
            }
        }
        return null;
    }

    function _fallbackEntry(value, matcher, matchedBy) {
        var alias = AppIdentity.aliasFor([value], Shell.ShellConfig.appIdAliases);
        if (alias !== null && alias.target.length > 0) {
            let aliasedEntry = root._entryById(alias.target);
            if (aliasedEntry !== null) {
                return {
                    entry: aliasedEntry,
                    matchedBy: "fallback-alias"
                };
            }
        }

        var entry = root._entryById(value);
        if (entry !== null) {
            return {
                entry: entry,
                matchedBy: "fallback-desktop-id"
            };
        }

        entry = DesktopEntries.heuristicLookup(value);
        if (entry !== null) {
            return {
                entry: entry,
                matchedBy: "fallback-heuristic"
            };
        }

        entry = root._firstModelMatch(value, matcher);
        return entry === null ? null : {
            entry: entry,
            matchedBy: matchedBy
        };
    }

    function _firstFallback(hints) {
        var match = null;
        var applicationName = AppIdentity.text(hints.applicationName);
        if (applicationName.length > 0) {
            match = root._fallbackEntry(applicationName, AppIdentity.entryMatchesName, "fallback-name");
            if (match !== null) {
                return match;
            }
        }

        var processBinary = AppIdentity.text(hints.processBinary);
        if (processBinary.length > 0) {
            match = root._fallbackEntry(processBinary, AppIdentity.entryMatchesExecutable, "fallback-executable");
            if (match !== null) {
                return match;
            }
        }

        var fallbackName = AppIdentity.text(hints.fallbackName);
        if (fallbackName.length > 0) {
            match = root._fallbackEntry(fallbackName, AppIdentity.entryMatchesName, "fallback-name");
            if (match !== null) {
                return match;
            }
        }
        return null;
    }

    function _result(entry, canonicalId, originalId, hints, matchedBy) {
        var requestedIcon = AppIdentity.text(hints.iconName);
        var entryIcon = entry === null ? "" : AppIdentity.text(entry.icon);
        var iconName = requestedIcon || entryIcon || root.fallbackIcon;
        var displayName = entry === null ? (AppIdentity.text(hints.applicationName) || AppIdentity.text(hints.fallbackName) || originalId || "Unknown application") : entry.name;

        return {
            canonicalId: canonicalId,
            desktopId: entry === null ? "" : entry.id,
            desktopEntry: entry,
            displayName: displayName,
            iconName: iconName,
            iconPath: root._iconPath([requestedIcon, entryIcon], AppIdentity.text(hints.appId) || originalId),
            matchedBy: matchedBy,
            originalId: originalId
        };
    }

    function resolveIdentity(hints) {
        var currentRevision = root.revision;
        hints = hints && typeof hints === "object" ? hints : {};

        var primaryValues = AppIdentity.primaryCandidates(hints);
        var values = AppIdentity.candidates(hints);
        var originalId = values.length === 0 ? "" : values[0];
        var alias = AppIdentity.aliasFor(primaryValues, Shell.ShellConfig.appIdAliases);
        var entry;

        if (alias !== null && alias.target.length > 0) {
            entry = root._entryById(alias.target);
            if (entry !== null) {
                return root._result(entry, entry.id, originalId, hints, "alias");
            }

            let unresolved = root._result(null, alias.target, originalId, hints, "alias");
            unresolved.desktopId = alias.target;
            return unresolved;
        }

        entry = root._firstExact(primaryValues);
        if (entry !== null) {
            return root._result(entry, entry.id, originalId, hints, "desktop-id");
        }

        entry = root._firstHeuristic(primaryValues);
        if (entry !== null) {
            return root._result(entry, entry.id, originalId, hints, "heuristic");
        }

        var fallback = root._firstFallback(hints);
        if (fallback !== null) {
            return root._result(fallback.entry, fallback.entry.id, originalId, hints, fallback.matchedBy);
        }

        return root._result(null, AppIdentity.fallbackId(values), originalId, hints, "fallback");
    }

    // Resolutions are memoised per desktop-entry revision. Reading revision
    // here also keeps callers' bindings dependent on it.
    function _identityCache() {
        var cache = root._identityCacheStore;
        if (cache.revision !== root.revision || cache.size > 512) {
            cache.revision = root.revision;
            cache.size = 0;
            cache.entries = Object.create(null);
        }
        return cache;
    }

    function _memoised(key, resolve) {
        var cache = root._identityCache();
        if (!(key in cache.entries)) {
            cache.entries[key] = resolve();
            cache.size += 1;
        }
        return cache.entries[key];
    }

    function _windowIdentity(appId, title) {
        // A window that resolves through its app ID alone does not depend on
        // its title, so the title only joins the key for unmatched app IDs.
        var primary = appId.length === 0 ? null : root._memoised("window-app\n" + appId, function () {
            var result = root.resolveIdentity({
                appId: appId
            });
            return result.desktopEntry === null ? null : result;
        });
        if (primary !== null) {
            return primary;
        }
        return root._memoised("window\n" + appId + "\n" + title, function () {
            return root.resolveIdentity({
                appId: appId,
                applicationName: title
            });
        });
    }

    function resolveWindow(window) {
        var appId = root._value(window, ["app_id", "appId"]);
        var result = Object.assign({}, root._windowIdentity(appId, root._value(window, ["title"])));
        var canonicalId = AppIdentity.windowCanonicalId(result, appId, root._value(window, ["id"]));
        if (canonicalId !== result.canonicalId) {
            result.canonicalId = canonicalId;
            result.matchedBy = "niri-window-id";
        }
        return result;
    }

    function resolveDesktopId(desktopId) {
        var normalized = AppIdentity.text(desktopId);
        return Object.assign({}, root._memoised("desktop\n" + normalized, function () {
            return root.resolveIdentity({
                appId: normalized,
                fallbackName: normalized
            });
        }));
    }

    function resolveStream(stream) {
        return root.resolveIdentity({
            applicationId: root._streamValue(stream, ["application.id", "applicationId", "appId"]),
            applicationName: root._streamValue(stream, ["application.name", "applicationName", "name"]),
            processBinary: root._streamValue(stream, ["application.process.binary", "processBinary", "binary"]),
            iconName: root._streamValue(stream, ["application.icon-name", "iconName"]),
            fallbackName: root._streamValue(stream, ["media.name", "mediaName"])
        });
    }

    function desktopEntryFor(id) {
        var currentRevision = root.revision;
        var normalized = AppIdentity.text(id);
        if (normalized.length === 0) {
            return null;
        }

        var alias = AppIdentity.aliasFor([normalized], Shell.ShellConfig.appIdAliases);
        if (alias !== null && alias.target.length > 0) {
            return root._entryById(alias.target);
        }

        var exact = root._entryById(normalized);
        return exact === null ? DesktopEntries.heuristicLookup(normalized) : exact;
    }

    function iconPathForWindow(window) {
        return root.resolveWindow(window).iconPath;
    }

    function _launchCommand(entry) {
        return LaunchCommand.uwsmAppService(Shell.ShellConfig.appLauncher, entry.id);
    }

    function launchDesktopId(id) {
        var normalized = AppIdentity.text(id);
        var entry = root.desktopEntryFor(normalized);

        if (normalized.length === 0) {
            root._reportLaunchFailure(normalized, "desktop ID is empty");
            return false;
        }
        if (entry === null) {
            root._reportLaunchFailure(normalized, "desktop entry was not found");
            return false;
        }
        if (!entry.command || entry.command.length === 0) {
            root._reportLaunchFailure(entry.id, "desktop entry has no executable command");
            return false;
        }
        if (root.isLaunchPending(entry.id)) {
            return false;
        }

        var process = launchProcessComponent.createObject(root, {
            desktopId: entry.id
        });
        if (!process) {
            root._reportLaunchFailure(entry.id, "the isolated desktop-entry launcher could not be created");
            return false;
        }

        root.clearLaunchFailure();
        root._beginLaunch(process);
        try {
            process.command = root._launchCommand(entry); // qmllint disable missing-property
            process.running = true; // qmllint disable missing-property
        } catch (launchError) {
            root._endLaunch(process);
            process.completed = true; // qmllint disable missing-property
            process.destroy();
            root._reportLaunchFailure(entry.id, "could not launch desktop entry: " + launchError);
            return false;
        }

        root.launchRequested(entry.id);
        return true;
    }

    function _disposeLaunch(process) {
        if (!process) {
            return;
        }
        root._endLaunch(process);
        if (process.completed) {
            return;
        }
        process.completed = true;
        process.destroy();
    }

    function _launchProcessFailedToStart(process) {
        if (!process || process.completed) {
            return;
        }
        root._endLaunch(process);
        root._reportLaunchFailure(process.desktopId, "the isolated desktop-entry launcher could not be started");
        root._disposeLaunch(process);
    }

    function _launchProcessExited(process, exitCode) {
        if (!process || process.completed) {
            return;
        }
        if (exitCode !== 0) {
            let detail = String(process.errorText || "").trim();
            root._endLaunch(process);
            root._reportLaunchFailure(process.desktopId, detail || "desktop-entry launcher exited with code " + exitCode);
        } else {
            root._endLaunch(process);
            root._reportLaunchSuccess(process.desktopId);
        }
        root._disposeLaunch(process);
    }

    function _launchProcessTimedOut(process) {
        if (!process || process.completed) {
            return;
        }
        root._endLaunch(process);
        root._reportLaunchFailure(process.desktopId, "desktop-entry launcher did not complete its start job within 7 seconds");
        process.completed = true;
        if (process.running) {
            process.running = false;
        }
        process.destroy();
    }

    property Connections _desktopEntryConnections: Connections {
        target: DesktopEntries
        function onApplicationsChanged() {
            root.revision += 1;
        }
    }

    property Component _launchProcessComponent: Component {
        id: launchProcessComponent

        Process {
            id: launchProcess
            property string desktopId: ""
            property alias errorText: errorCollector.text
            property bool startedSuccessfully: false
            property bool completed: false
            property bool pendingRegistered: false

            stdout: StdioCollector {}
            stderr: StdioCollector {
                id: errorCollector
            }

            onStarted: startedSuccessfully = true

            onRunningChanged: {
                if (!running && !startedSuccessfully && !completed) {
                    Qt.callLater(function () {
                        if (!launchProcess.running && !launchProcess.startedSuccessfully && !launchProcess.completed) {
                            root._launchProcessFailedToStart(launchProcess);
                        }
                    });
                }
            }

            onExited: function (exitCode) { // qmllint disable signal-handler-parameters
                root._launchProcessExited(launchProcess, exitCode);
            }

            property Timer _timeout: Timer {
                interval: 7000
                running: launchProcess.running && !launchProcess.completed
                onTriggered: root._launchProcessTimedOut(launchProcess)
            }
        }
    }
}
