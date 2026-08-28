function createState() {
    return {
        phase: "closed",
        generation: 0,
        item: null,
        menu: null,
        anchor: null
    };
}

function requestOpen(state, item, menu, anchor) {
    if (!state || !item || !menu || !anchor)
        return { action: "reject", token: 0 };
    if (inputClaimed(state) && state.item === item)
        return { action: "close", token: state.generation };

    var switching = inputClaimed(state) && state.item !== null;
    state.generation += 1;
    state.phase = switching ? "switching" : "opening";
    state.item = item;
    state.menu = menu;
    state.anchor = anchor;
    return {
        action: switching ? "switch" : "open",
        token: state.generation
    };
}

function markOpen(state, token) {
    if (!matches(state, token) || !inputClaimed(state))
        return false;
    state.phase = "open";
    return true;
}

function beginClose(state) {
    if (!state || state.phase === "closed" || state.phase === "closing")
        return 0;
    state.generation += 1;
    state.phase = "closing";
    return state.generation;
}

function finishClose(state, token) {
    if (!matches(state, token) || state.phase !== "closing")
        return false;
    state.phase = "closed";
    state.item = null;
    state.menu = null;
    state.anchor = null;
    return true;
}

function matches(state, token) {
    return !!state && state.generation === Number(token);
}

function ownsItem(state, item) {
    return !!state && state.item === item && state.phase !== "closed";
}

function ownsAnchor(state, anchor) {
    return !!state && state.anchor === anchor && state.phase !== "closed";
}

function inputClaimed(state) {
    return !!state && (state.phase === "opening" || state.phase === "open" || state.phase === "switching");
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        beginClose: beginClose,
        createState: createState,
        finishClose: finishClose,
        inputClaimed: inputClaimed,
        markOpen: markOpen,
        matches: matches,
        ownsAnchor: ownsAnchor,
        ownsItem: ownsItem,
        requestOpen: requestOpen
    };
}
