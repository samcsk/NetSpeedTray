// Only the percentage next to the English Weekly limit heading belongs to this card.
function readWeeklyCard(visibleText) {
    const heading = /^\s*Weekly limit\s*$/im.exec(visibleText);
    if (!heading) return null;
    // A neighboring time window can render inline. Match its label, not a word in reset copy.
    const rest = visibleText.slice(heading.index + heading[0].length).trimStart();
    const card = rest.split(/\b\d+[\p{Dash}\s]+(?:hours?|days?|weeks?)\s+(?:limits?|quotas?)\b/iu, 1)[0];
    // A wrapped duration can span several lines in the card's visible text.
    const fields = card.replace(/^Resets\s+in\s+(?:\d+\s*[dhm]\b[\s,]*)+(?=\d+%)/i, "");
    const percent = /^(?:Resets?\b[^\r\n%]*?\s+)?(\d{1,3})%\s+left\b/i.exec(fields);
    if (!percent) return null;
    const left = Number(percent[1]);
    return left <= 100 ? {left} : null;
}

function readWeeklyPage(root) {
    const selector = "article, section, li, [role='group'], [role='region']";
    const peers = new Set();
    const branches = new Set();
    const weeklyCards = [];
    for (const region of root.querySelectorAll(selector)) {
        if (!region.checkVisibility()) continue;
        const text = region.innerText;
        if (/^\s*Weekly limit\s*$/im.test(text)) {
            if (region.matches("article, section, li, [role='region']")) weeklyCards.push(region);
            continue;
        }
        if (!/\d\s*%\s+left\b/i.test(text)) continue;
        if (!region.querySelector("h1,h2,h3,h4,h5,h6,[role='heading']") &&
            !/\b(?:limit|quota)s?\b/i.test(text)) continue;
        peers.add(region);
        for (let parent = region.parentElement; parent && root.contains(parent); parent = parent.parentElement) {
            branches.add(parent);
        }
    }
    const card = weeklyCards.reverse().find(region => !branches.has(region));
    if (card) return readWeeklyCard(card.innerText);
    if (!peers.size) return readWeeklyCard(root.innerText);

    // Read contiguous fields on either side of peer cards. Each peer ends a block
    // before its first field, even when its percentage comes before its heading.
    const blocks = [[]];
    function visit(node) {
        if (peers.has(node)) {
            blocks.push([]);
        } else if (branches.has(node) ||
                   (node instanceof HTMLElement && getComputedStyle(node).display === "contents")) {
            node.childNodes.forEach(visit);
        } else if (node.nodeType === Node.TEXT_NODE) {
            blocks.at(-1).push(node.textContent);
        } else if (node instanceof HTMLElement && node.checkVisibility()) {
            blocks.at(-1).push(node.innerText);
        }
    }
    visit(root);
    for (const fields of blocks) {
        const balance = readWeeklyCard(fields.join("\n"));
        if (balance) return balance;
    }
    return null;
}
