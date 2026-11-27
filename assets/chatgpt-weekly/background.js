importScripts("folder.js");
const USAGE = "https://chatgpt.com/settings/usage";
async function usageTabs() {
    return (await chrome.tabs.query({url: USAGE + "*"})).filter(tab =>
        new URL(tab.url).pathname.replace(/\/$/, "") === "/settings/usage");
}

async function sync() {
    const connection = await connectionFolder();
    if (!connection) return;
    const {folder, id} = connection;
    if (await folder.queryPermission({mode: "readwrite"}) !== "granted") return;
    const active = await readActive(folder);
    if (!active) return;
    const owner = await (await folder.getFileHandle("browser.json")).getFile();
    if (owner.size > 64 || JSON.parse(await owner.text()) !== id) return;
    async function publish(weekly) {
        const handle = await folder.getFileHandle("weekly-" + id + ".json", {create: true});
        const stream = await handle.createWritable();
        await stream.write(JSON.stringify({session: active.session, weekly}));
        await stream.close();
    }
    const tabs = await usageTabs();
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
    if (message === "open" && sender.url === chrome.runtime.getURL("connect.html")) openUsage();
});
async function openUsage() {
    const connection = await connectionFolder();
    if (!connection || await connection.folder.queryPermission({mode: "readwrite"}) !== "granted") {
        await chrome.runtime.openOptionsPage();
        return;
    }
    const [tab] = await usageTabs();
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
}
chrome.action.onClicked.addListener(openUsage);
