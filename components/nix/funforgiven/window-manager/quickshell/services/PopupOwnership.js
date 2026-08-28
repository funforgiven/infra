function createState() {
    return {
        phase: "closed",
        generation: 0,
        kind: "",
        owner: null,
        screen: null
    };
}

function requestOpen(state, kind, owner, screen) {
    if (!state || !owner || String(kind || "").length === 0)
        return { accepted: false, token: 0, previousOwner: null, previousToken: 0 };

    var previousOwner = state.owner;
    var previousToken = state.generation;
    var replacingOwner = previousOwner !== null && previousOwner !== owner;

    state.generation += 1;
    state.phase = replacingOwner ? "switching" : "opening";
    state.kind = String(kind);
    state.owner = owner;
    state.screen = screen || null;

    return {
        accepted: true,
        token: state.generation,
        previousOwner: replacingOwner ? previousOwner : null,
        previousToken: replacingOwner ? previousToken : 0
    };
}

function markOpen(state, owner, token) {
    if (!isCurrent(state, owner, token))
        return false;
    state.phase = "open";
    return true;
}

function beginClose(state, owner, token) {
    if (!isCurrent(state, owner, token))
        return false;
    state.phase = "closing";
    return true;
}

function finishClose(state, owner, token) {
    if (!isCurrent(state, owner, token))
        return false;
    state.phase = "closed";
    state.kind = "";
    state.owner = null;
    state.screen = null;
    return true;
}

function forgetOwner(state, owner) {
    if (!state || state.owner !== owner)
        return false;
    state.generation += 1;
    state.phase = "closed";
    state.kind = "";
    state.owner = null;
    state.screen = null;
    return true;
}

function isCurrent(state, owner, token) {
    return !!state && state.owner === owner && state.generation === Number(token);
}

function inputClaimed(state) {
    return !!state && (state.phase === "opening" || state.phase === "open" || state.phase === "switching");
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        beginClose: beginClose,
        createState: createState,
        finishClose: finishClose,
        forgetOwner: forgetOwner,
        inputClaimed: inputClaimed,
        isCurrent: isCurrent,
        markOpen: markOpen,
        requestOpen: requestOpen
    };
}
