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
        status.textContent = "Connected. Keep one signed-in English usage tab open.";
        document.querySelector("#usage").hidden = false;
    } catch (error) {
        if (error.name !== "AbortError") {
            status.textContent = "Enable and save ChatGPT weekly limit, then choose its folder and allow access.";
        }
    }
});
document.querySelector("#usage").addEventListener("click", () => chrome.runtime.sendMessage("open"));
