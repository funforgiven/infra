function resolve(theme, state) {
    state = state || {};
    if (state.enabled === false)
        return theme.symbolicIconDisabled;
    if (state.destructive === true || state.attention === true)
        return theme.symbolicIconDestructive;
    if (state.warning === true)
        return theme.symbolicIconWarning;
    if (state.active === true || state.selected === true || state.checked === true)
        return theme.symbolicIconActive;
    if (state.pressed === true)
        return theme.symbolicIconPressed;
    if (state.hovered === true)
        return theme.symbolicIconHover;
    if (state.muted === true)
        return theme.symbolicIconMuted;
    return theme.symbolicIconForeground;
}

function preservesSourceColors(iconKind) {
    return iconKind === "application";
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        resolve: resolve,
        preservesSourceColors: preservesSourceColors
    };
}
