const assert = require("node:assert/strict");
const test = require("node:test");

const IconPolicy = require("../components/IconPolicy.js");

const theme = {
    symbolicIconForeground: "foreground",
    symbolicIconMuted: "muted",
    symbolicIconHover: "hover",
    symbolicIconPressed: "pressed",
    symbolicIconActive: "active",
    symbolicIconDisabled: "disabled",
    symbolicIconWarning: "warning",
    symbolicIconDestructive: "destructive"
};

test("symbolic icon states resolve through semantic theme roles", () => {
    assert.equal(IconPolicy.resolve(theme, {}), "foreground");
    assert.equal(IconPolicy.resolve(theme, { muted: true }), "muted");
    assert.equal(IconPolicy.resolve(theme, { hovered: true }), "hover");
    assert.equal(IconPolicy.resolve(theme, { pressed: true }), "pressed");
    assert.equal(IconPolicy.resolve(theme, { active: true }), "active");
    assert.equal(IconPolicy.resolve(theme, { checked: true }), "active");
    assert.equal(IconPolicy.resolve(theme, { warning: true }), "warning");
    assert.equal(IconPolicy.resolve(theme, { destructive: true }), "destructive");
    assert.equal(IconPolicy.resolve(theme, { enabled: false, active: true }), "disabled");
});

test("higher-severity symbolic roles are deterministic", () => {
    assert.equal(IconPolicy.resolve(theme, { hovered: true, pressed: true }), "pressed");
    assert.equal(IconPolicy.resolve(theme, { pressed: true, active: true }), "active");
    assert.equal(IconPolicy.resolve(theme, { active: true, warning: true }), "warning");
    assert.equal(IconPolicy.resolve(theme, { warning: true, destructive: true }), "destructive");
});

test("only multicolor application icons preserve their source colors", () => {
    assert.equal(IconPolicy.preservesSourceColors("application"), true);
    assert.equal(IconPolicy.preservesSourceColors("symbolic"), false);
    assert.equal(IconPolicy.preservesSourceColors("status"), false);
});
