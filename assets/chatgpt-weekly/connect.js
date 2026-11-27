const restore = document.querySelector("#restore");
const statusText = document.querySelector("#status");
const usage = document.querySelector("#usage");
let saved;

function connected() {
    restore.hidden = true;
    usage.hidden = false;
    statusText.textContent = "Connected. Keep one signed-in English usage tab open.";
    chrome.action.setBadgeText({text: ""});
}

async function showSavedState() {
    if (await isPaired(saved)) {
        connected();
    } else {
        restore.hidden = true;
        usage.hidden = true;
        statusText.textContent = "This profile is no longer connected. Choose the widget folder to use this profile.";
    }
}

connectionFolder().then(async connection => {
    if (!connection) return;
    saved = connection;
    if (await saved.folder.queryPermission({mode: "readwrite"}) === "granted") {
        await showSavedState();
    } else {
        restore.hidden = false;
        statusText.textContent = "Allow the saved folder again. Choose “Allow on every visit” if your browser offers it.";
    }
});

restore.addEventListener("click", async () => {
    try {
        if (await saved.folder.requestPermission({mode: "readwrite"}) === "granted") {
            await showSavedState();
            return;
        }
    } catch {}
    statusText.textContent = "Folder access was not granted. You can choose the widget folder again.";
});

document.querySelector("#connect").addEventListener("click", async () => {
    const status = document.querySelector("#status");
    try {
        const folder = await showDirectoryPicker({mode: "readwrite"});
        if (!await readActive(folder)) throw new Error("inactive");
        const id = crypto.randomUUID().replaceAll("-", "");
        const owner = await folder.getFileHandle("browser.json", {create: true});
        const stream = await owner.createWritable();
        await stream.write(JSON.stringify(id));
        await stream.close();
        await connectionFolder({folder, id});
        connected();
    } catch (error) {
        if (error.name !== "AbortError") {
            status.textContent = "Enable and save ChatGPT weekly limit, then choose its folder and allow access.";
        }
    }
});
document.querySelector("#usage").addEventListener("click", () => chrome.runtime.sendMessage("open"));
