// File System Access grants are scoped to the directory the user selects in the picker.
async function connectionFolder(save) {
    const db = await new Promise((resolve, reject) => {
        const req = indexedDB.open("weekly-limit", 1);
        req.onupgradeneeded = () => req.result.createObjectStore("connection");
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
    try {
        return await new Promise((resolve, reject) => {
            const tx = db.transaction("connection", save ? "readwrite" : "readonly");
            const store = tx.objectStore("connection");
            const req = save ? store.put(save, "folder") : store.get("folder");
            tx.oncomplete = () => resolve(req.result);
            tx.onabort = () => reject(tx.error);
        });
    } finally {
        db.close();
    }
}

async function readActive(folder) {
    const handle = await folder.getFileHandle("active.json");
    const file = await handle.getFile();
    if (file.size > 256) return null;
    const data = JSON.parse(await file.text());
    const age = Date.now() / 1000 - data.time;
    return /^[a-f0-9]{32}$/.test(data.session) && age >= -2 && age < 90 ? data : null;
}
