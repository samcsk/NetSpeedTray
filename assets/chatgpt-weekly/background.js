const USAGE = "https://chatgpt.com/codex/settings/usage";
const LOCAL = "http://127.0.0.1:42179";

async function send(path, data) {
    const response = await fetch(LOCAL + path, {
        method: "POST", body: data, credentials: "omit", redirect: "error",
        cache: "no-store", signal: AbortSignal.timeout(3000)
    });
    return response.status === 204;
}

async function sync() {
    if (!await send("/ready")) return;
    const tabs = (await chrome.tabs.query({url: USAGE + "*"})).filter(tab =>
        new URL(tab.url).pathname.replace(/\/$/, "") === "/codex/settings/usage");
    if (tabs.length !== 1) {
        if (tabs.length > 1) await send("/weekly", "null");
        return;
    }
    const tabId = tabs[0].id;
    const result = await chrome.tabs.sendMessage(tabId, "read", {frameId: 0});
    if (result && await send("/weekly", JSON.stringify(result.weekly))) {
        await chrome.tabs.sendMessage(tabId, "refresh", {frameId: 0});
    }
}

function tick() {
    // Closed widget, disabled provider, signed-out redirect or a discarded tab.
    sync().catch(() => {});
}

function start() {
    chrome.alarms.create("weekly", {periodInMinutes: 1});
    tick();
}

chrome.runtime.onInstalled.addListener(start);
chrome.runtime.onStartup.addListener(start);
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "weekly") tick(); });
chrome.runtime.onMessage.addListener((message, sender) => {
    if (message === "ready" && sender.tab && sender.frameId === 0) tick();
});
chrome.action.onClicked.addListener(async () => {
    const [tab] = await chrome.tabs.query({url: USAGE});
    if (tab) {
        await chrome.tabs.update(tab.id, {active: true});
        await chrome.windows.update(tab.windowId, {focused: true});
    } else {
        await chrome.tabs.create({url: USAGE});
    }
});
