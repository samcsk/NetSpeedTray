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
    const regions = Array.from(root.querySelectorAll(selector)).filter(el => el.checkVisibility());
    const weeklyHeading = /^\s*Weekly limit\s*$/im;
    const weekly = regions.filter(el => weeklyHeading.test(el.innerText)).reverse();
    // An enclosing group may hold the heading and balance in separate children.
    // Stop expanding before a sibling card could contribute its own balance.
    const peers = regions.filter(el => !weeklyHeading.test(el.innerText) &&
        /\d\s*%\s+left\b/i.test(el.innerText) &&
        (el.querySelector("h1,h2,h3,h4,h5,h6,[role='heading']") ||
         /\b(?:limit|quota)s?\b/i.test(el.innerText)));
    for (const region of [...weekly, root]) {
        if (peers.some(peer => region.contains(peer))) continue;
        const balance = readWeeklyCard(region.innerText);
        if (balance) return balance;
    }
    return null;
}
