chrome.runtime.onMessage.addListener((action, sender, reply) => {
    if (sender.id !== chrome.runtime.id || location.pathname.replace(/\/$/, "") !== "/codex/settings/usage") return;
    if (action === "read") {
        reply({weekly: readWeeklyCard(document.body.innerText)});
    } else if (action === "refresh" && performance.now() >= 5 * 60_000) {
        location.reload();
    }
});
chrome.runtime.sendMessage("ready").catch(() => {});
