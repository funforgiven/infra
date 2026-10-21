function emptyIndex() {
    return Object.create(null);
}

function owns(object, property) {
    return object !== null
        && typeof object === "object"
        && Object.prototype.hasOwnProperty.call(object, property);
}

function cloneValue(value) {
    var clone;
    var keys;

    if (Array.isArray(value)) {
        return value.map(cloneValue);
    }

    if (value === null || typeof value !== "object") {
        return value;
    }

    clone = {};
    keys = Object.keys(value);
    for (var index = 0; index < keys.length; index += 1) {
        clone[keys[index]] = cloneValue(value[keys[index]]);
    }
    return clone;
}

function isId(value) {
    if (typeof value === "number") {
        return isFinite(value) && value >= 0;
    }

    return typeof value === "string" && value.length > 0;
}

function idKey(value) {
    return typeof value + ":" + String(value);
}

function sameId(left, right) {
    return isId(left) && isId(right) && idKey(left) === idKey(right);
}

function shallowIndex(source) {
    var target = emptyIndex();
    var keys = source && typeof source === "object" ? Object.keys(source) : [];

    for (var index = 0; index < keys.length; index += 1) {
        target[keys[index]] = source[keys[index]];
    }
    return target;
}

function shallowEntry(source) {
    var target = {};
    var keys = Object.keys(source);

    for (var index = 0; index < keys.length; index += 1) {
        target[keys[index]] = source[keys[index]];
    }
    return target;
}

// Reducer states share their indexes and entries structurally: an event copies
// only the index it touches and only the entries it changes. Entries are never
// mutated after they are reachable from a returned state, so nested values may
// be shared between generations as long as they are replaced, not edited.
function writableIndex(next, previous, field) {
    if (next[field] === previous[field]) {
        next[field] = shallowIndex(previous[field]);
    }
    return next[field];
}

function setEntryField(next, previous, field, key, property, value) {
    var entry = next[field][key];
    if (!entry || entry[property] === value) {
        return;
    }

    var index = writableIndex(next, previous, field);
    if (previous[field] && entry === previous[field][key]) {
        entry = shallowEntry(entry);
        index[key] = entry;
    }
    entry[property] = value;
}

function replacementIndex(items) {
    var target = emptyIndex();

    for (var index = 0; index < items.length; index += 1) {
        var item = items[index];
        if (item !== null && typeof item === "object" && isId(item.id)) {
            target[idKey(item.id)] = cloneValue(item);
        }
    }
    return target;
}

function createState() {
    return {
        _workspaces: emptyIndex(),
        _windows: emptyIndex(),
        _initialWorkspacesReceived: false,
        _initialWindowsReceived: false,
        configLoaded: false,
        configFailed: false,
        connected: false,
        stale: true,
        error: null,
        generation: 0
    };
}

function copyState(state) {
    if (state === null || typeof state !== "object") {
        return createState();
    }

    return {
        _workspaces: state._workspaces || emptyIndex(),
        _windows: state._windows || emptyIndex(),
        _initialWorkspacesReceived: state._initialWorkspacesReceived === true,
        _initialWindowsReceived: state._initialWindowsReceived === true,
        configLoaded: state.configLoaded === true,
        configFailed: state.configFailed === true,
        connected: state.connected === true,
        stale: state.stale !== false,
        error: state.error === undefined ? null : state.error,
        generation: typeof state.generation === "number" ? state.generation : 0
    };
}

function errorMessage(error) {
    if (error === undefined || error === null || error === "") {
        return null;
    }
    if (typeof error === "string") {
        return error;
    }
    if (typeof error.message === "string") {
        return error.message;
    }
    return String(error);
}

function connectionOpened(previousState) {
    var state = createState();
    var previousGeneration = previousState
        && typeof previousState.generation === "number"
        ? previousState.generation
        : 0;

    state.connected = true;
    state.generation = previousGeneration + 1;
    return state;
}

function connectionClosed(state, error) {
    var next = copyState(state);
    next.connected = false;
    next.stale = true;
    next.error = errorMessage(error);
    return next;
}

function connectionError(state, error) {
    return connectionClosed(state, error);
}

function compareText(left, right) {
    var leftMissing = left === null || left === undefined;
    var rightMissing = right === null || right === undefined;

    if (leftMissing && rightMissing) {
        return 0;
    }
    if (leftMissing) {
        return 1;
    }
    if (rightMissing) {
        return -1;
    }

    left = String(left);
    right = String(right);
    if (left < right) {
        return -1;
    }
    if (left > right) {
        return 1;
    }
    return 0;
}

function compareNumber(left, right) {
    var leftNumber = typeof left === "number" && isFinite(left) ? left : null;
    var rightNumber = typeof right === "number" && isFinite(right) ? right : null;

    if (leftNumber === null || rightNumber === null) {
        return compareText(left, right);
    }
    if (leftNumber < rightNumber) {
        return -1;
    }
    if (leftNumber > rightNumber) {
        return 1;
    }
    return 0;
}

function compareWorkspace(left, right) {
    return compareText(left.output, right.output)
        || compareNumber(left.idx, right.idx)
        || compareNumber(left.id, right.id);
}

function scrollingPosition(window) {
    var layout = window && window.layout;
    var position = layout && layout.pos_in_scrolling_layout;
    return Array.isArray(position) ? position : [null, null];
}

function compareWindow(left, right) {
    var leftPosition = scrollingPosition(left);
    var rightPosition = scrollingPosition(right);

    return compareNumber(left.workspace_id, right.workspace_id)
        || compareNumber(leftPosition[0], rightPosition[0])
        || compareNumber(leftPosition[1], rightPosition[1])
        || compareNumber(left.id, right.id);
}

function sortedValues(index, compare) {
    var keys = Object.keys(index);
    var values = [];

    for (var position = 0; position < keys.length; position += 1) {
        values.push(cloneValue(index[keys[position]]));
    }
    values.sort(compare);
    return values;
}

function publishedValues(index, previous, field, compare) {
    if (previous && previous._sources && previous._sources[field] === index) {
        return previous[field];
    }
    return sortedValues(index, compare);
}

// Pass the previous publication to reuse its workspace or window list when the
// corresponding reducer index has not changed since that publication.
function publish(state, previous) {
    state = state && typeof state === "object" ? state : createState();
    var workspaceIndex = state._workspaces || emptyIndex();
    var windowIndex = state._windows || emptyIndex();
    var view = {
        workspaces: publishedValues(workspaceIndex, previous, "workspaces", compareWorkspace),
        windows: publishedValues(windowIndex, previous, "windows", compareWindow),
        configLoaded: state.configLoaded === true,
        configFailed: state.configFailed === true,
        connected: state.connected === true,
        stale: state.stale !== false,
        error: state.error === undefined ? null : state.error,
        generation: typeof state.generation === "number" ? state.generation : 0
    };

    Object.defineProperty(view, "_sources", {
        value: {
            workspaces: workspaceIndex,
            windows: windowIndex
        }
    });
    return view;
}

function applyWorkspacesChanged(next, payload) {
    if (!payload || !Array.isArray(payload.workspaces)) {
        return false;
    }
    next._workspaces = replacementIndex(payload.workspaces);
    next._initialWorkspacesReceived = true;
    return true;
}

function applyWorkspaceUrgencyChanged(next, payload, previous) {
    if (!payload || !isId(payload.id) || typeof payload.urgent !== "boolean") {
        return false;
    }

    var key = idKey(payload.id);
    if (!next._workspaces[key]) {
        return false;
    }
    setEntryField(next, previous, "_workspaces", key, "is_urgent", payload.urgent);
    return true;
}

function applyWorkspaceActivated(next, payload, previous) {
    if (!payload || !isId(payload.id) || typeof payload.focused !== "boolean") {
        return false;
    }

    var target = next._workspaces[idKey(payload.id)];
    if (!target) {
        return false;
    }

    var keys = Object.keys(next._workspaces);
    for (var index = 0; index < keys.length; index += 1) {
        var workspace = next._workspaces[keys[index]];
        var activated = sameId(workspace.id, payload.id);

        if (workspace.output === target.output) {
            setEntryField(next, previous, "_workspaces", keys[index], "is_active", activated);
        }
        if (payload.focused) {
            setEntryField(next, previous, "_workspaces", keys[index], "is_focused", activated);
        }
    }
    return true;
}

function applyWorkspaceActiveWindowChanged(next, payload, previous) {
    if (!payload
        || !isId(payload.workspace_id)
        || !owns(payload, "active_window_id")
        || (payload.active_window_id !== null && !isId(payload.active_window_id))) {
        return false;
    }

    var key = idKey(payload.workspace_id);
    if (!next._workspaces[key]) {
        return false;
    }
    setEntryField(next, previous, "_workspaces", key, "active_window_id", payload.active_window_id);
    return true;
}

function applyWindowsChanged(next, payload) {
    if (!payload || !Array.isArray(payload.windows)) {
        return false;
    }
    next._windows = replacementIndex(payload.windows);
    next._initialWindowsReceived = true;
    return true;
}

function applyWindowOpenedOrChanged(next, payload, previous) {
    if (!payload
        || !payload.window
        || typeof payload.window !== "object"
        || !isId(payload.window.id)) {
        return false;
    }

    var window = cloneValue(payload.window);
    writableIndex(next, previous, "_windows")[idKey(window.id)] = window;

    if (window.is_focused === true) {
        var keys = Object.keys(next._windows);
        for (var index = 0; index < keys.length; index += 1) {
            if (!sameId(next._windows[keys[index]].id, window.id)) {
                setEntryField(next, previous, "_windows", keys[index], "is_focused", false);
            }
        }
    }
    return true;
}

function applyWindowClosed(next, payload, previous) {
    if (!payload || !isId(payload.id)) {
        return false;
    }

    var key = idKey(payload.id);
    if (!owns(next._windows, key)) {
        return false;
    }
    delete writableIndex(next, previous, "_windows")[key];
    return true;
}

function applyWindowFocusChanged(next, payload, previous) {
    if (!payload
        || !owns(payload, "id")
        || (payload.id !== null && !isId(payload.id))) {
        return false;
    }

    var keys = Object.keys(next._windows);
    for (var index = 0; index < keys.length; index += 1) {
        var focused = payload.id !== null && sameId(next._windows[keys[index]].id, payload.id);
        setEntryField(next, previous, "_windows", keys[index], "is_focused", focused);
    }
    return true;
}

function applyWindowFocusTimestampChanged(next, payload, previous) {
    if (!payload
        || !isId(payload.id)
        || !owns(payload, "focus_timestamp")
        || (payload.focus_timestamp !== null
            && typeof payload.focus_timestamp !== "object")) {
        return false;
    }

    var key = idKey(payload.id);
    if (!next._windows[key]) {
        return false;
    }
    setEntryField(next, previous, "_windows", key, "focus_timestamp", cloneValue(payload.focus_timestamp));
    return true;
}

function applyWindowUrgencyChanged(next, payload, previous) {
    if (!payload || !isId(payload.id) || typeof payload.urgent !== "boolean") {
        return false;
    }

    var key = idKey(payload.id);
    if (!next._windows[key]) {
        return false;
    }
    setEntryField(next, previous, "_windows", key, "is_urgent", payload.urgent);
    return true;
}

function applyWindowLayoutsChanged(next, payload, previous) {
    if (!payload || !Array.isArray(payload.changes)) {
        return false;
    }

    var changed = false;
    for (var index = 0; index < payload.changes.length; index += 1) {
        var pair = payload.changes[index];
        if (!Array.isArray(pair)
            || pair.length < 2
            || !isId(pair[0])
            || pair[1] === null
            || typeof pair[1] !== "object") {
            continue;
        }

        var key = idKey(pair[0]);
        if (next._windows[key]) {
            setEntryField(next, previous, "_windows", key, "layout", cloneValue(pair[1]));
            changed = true;
        }
    }
    return changed;
}

function applyConfigLoaded(next, payload) {
    if (!payload || typeof payload.failed !== "boolean") {
        return false;
    }
    next.configLoaded = true;
    next.configFailed = payload.failed;
    return true;
}

function reduce(state, event) {
    state = state && typeof state === "object" ? state : createState();
    if (event === null || typeof event !== "object" || Array.isArray(event)) {
        return state;
    }

    var next = copyState(state);
    var changed = false;

    if (owns(event, "WorkspacesChanged")) {
        changed = applyWorkspacesChanged(next, event.WorkspacesChanged);
    } else if (owns(event, "WorkspaceUrgencyChanged")) {
        changed = applyWorkspaceUrgencyChanged(next, event.WorkspaceUrgencyChanged, state);
    } else if (owns(event, "WorkspaceActivated")) {
        changed = applyWorkspaceActivated(next, event.WorkspaceActivated, state);
    } else if (owns(event, "WorkspaceActiveWindowChanged")) {
        changed = applyWorkspaceActiveWindowChanged(
            next,
            event.WorkspaceActiveWindowChanged,
            state
        );
    } else if (owns(event, "WindowsChanged")) {
        changed = applyWindowsChanged(next, event.WindowsChanged);
    } else if (owns(event, "WindowOpenedOrChanged")) {
        changed = applyWindowOpenedOrChanged(next, event.WindowOpenedOrChanged, state);
    } else if (owns(event, "WindowClosed")) {
        changed = applyWindowClosed(next, event.WindowClosed, state);
    } else if (owns(event, "WindowFocusChanged")) {
        changed = applyWindowFocusChanged(next, event.WindowFocusChanged, state);
    } else if (owns(event, "WindowFocusTimestampChanged")) {
        changed = applyWindowFocusTimestampChanged(
            next,
            event.WindowFocusTimestampChanged,
            state
        );
    } else if (owns(event, "WindowUrgencyChanged")) {
        changed = applyWindowUrgencyChanged(next, event.WindowUrgencyChanged, state);
    } else if (owns(event, "WindowLayoutsChanged")) {
        changed = applyWindowLayoutsChanged(next, event.WindowLayoutsChanged, state);
    } else if (owns(event, "ConfigLoaded")) {
        changed = applyConfigLoaded(next, event.ConfigLoaded);
    }

    if (changed
        && next.connected
        && next._initialWorkspacesReceived
        && next._initialWindowsReceived) {
        next.stale = false;
    }

    return changed ? next : state;
}

function reduceAll(state, events) {
    if (!Array.isArray(events)) {
        return state;
    }
    for (var index = 0; index < events.length; index += 1) {
        state = reduce(state, events[index]);
    }
    return state;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        createState: createState,
        connectionOpened: connectionOpened,
        connectionClosed: connectionClosed,
        connectionError: connectionError,
        publish: publish,
        reduce: reduce,
        reduceAll: reduceAll
    };
}
