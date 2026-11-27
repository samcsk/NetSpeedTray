document.querySelector("#connect").addEventListener("click", async () => {
    const status = document.querySelector("#status");
    try {
        const folder = await showDirectoryPicker({mode: "readwrite"});
        if (!await readActive(folder)) throw new Error("inactive");
        await connectionFolder(folder);
        status.textContent = "Connected. Keep one signed-in English usage tab open.";
        document.querySelector("#usage").hidden = false;
    } catch (error) {
        if (error.name !== "AbortError") {
            status.textContent = "Enable and save ChatGPT weekly limit, then choose its folder and allow access.";
        }
    }
});
