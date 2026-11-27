const {readFileSync} = require("node:fs");
const {runInNewContext} = require("node:vm");
const {join} = require("node:path");
const {test} = require("node:test");
const assert = require("node:assert/strict");
const script = readFileSync(join(__dirname, "../../assets/chatgpt-weekly/weekly.js"), "utf8");
const parse = text => JSON.parse(JSON.stringify(runInNewContext(script + "\nreadWeeklyCard(text)", {text})));

test("selects the weekly fields beside a five-hour limit and manual resets", () => {
    const result = parse("5-hour limit\nResets in 30m\n2% left\nWeekly limit\nResets in 1d 21h\n71% left\nUsage limit resets\nAvailable 3");
    assert.deepEqual(result, {left: 71});
    assert.deepEqual(parse("Weekly limit\nResets in\n1d\n21h\n71% left"), {left: 71});
    assert.deepEqual(parse("Weekly limit\nResets in 1d, 21h\n71% left"), {left: 71});
});
test("handles the opposite reading order and a zero balance", () => {
    assert.deepEqual(parse("Weekly limit\n0% left\nResets in 43m"), {left: 0});
});
test("reads the percentage when the card has no reset time", () => {
    assert.deepEqual(parse("Weekly limit\n100% left"), {left: 100});
    assert.deepEqual(parse("Weekly limit\nResets Monday at 3 PM\n13% left"), {left: 13});
    assert.deepEqual(parse("Weekly limit\nResets in 2 days 13% left"), {left: 13});
});
test("never substitutes another window or the available reset count", () => {
    assert.equal(parse("Weekly limit\nUsage limit resets\nAvailable 3\nResets in 1d 21h\n71% left"), null);
    assert.equal(parse("5-hour limit\nResets in 1h\n71% left"), null);
    assert.equal(parse("Weekly limit\nResets in 1h\n101% left"), null);
    assert.equal(parse("Weekly limit\nResets tomorrow\n5-hour limit\n71% left"), null);
    assert.equal(parse("Weekly limit\nResets tomorrow 5-hour limit 71% left"), null);
});
