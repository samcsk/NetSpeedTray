importScripts("folder.js");
const USAGE = "https://chatgpt.com/settings/usage";
async function sync() {
    const folder = await connectionFolder();
    if (!folder || await folder.queryPermission({mode: "readwrite"}) !== "granted") return;
    const active = await readActive(folder);
    if (!active) return;
    async function publish(weekly) {
        const handle = await folder.getFileHandle("weekly.json", {create: true});
        const stream = await handle.createWritable();
        await stream.write(JSON.stringify({session: active.session, weekly}));
        await stream.close();
    }
    const tabs = (await chrome.tabs.query({url: USAGE + "*"})).filter(tab =>
        new URL(tab.url).pathname.replace(/\/$/, "") === "/settings/usage");
    if (tabs.length !== 1) {
        if (tabs.length > 1) await publish(null);
        return;
    }
    const tabId = tabs[0].id;
    const result = await chrome.tabs.sendMessage(tabId, "read", {frameId: 0});
    if (result) {
        await publish(result.weekly);
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
    const folder = await connectionFolder();
    if (!folder || await folder.queryPermission({mode: "readwrite"}) !== "granted") {
        await chrome.runtime.openOptionsPage();
        return;
    }
    const [tab] = await chrome.tabs.query({url: USAGE});
    if (tab) {
        await chrome.tabs.update(tab.id, {active: true});
        await chrome.windows.update(tab.windowId, {focused: true});
        try {
            await chrome.tabs.sendMessage(tab.id, "read", {frameId: 0});
            tick();
        } catch {
            // Tabs already open at install time have not received the content script.
            await chrome.tabs.reload(tab.id);
        }
    } else {
        await chrome.tabs.create({url: USAGE});
    }
});
