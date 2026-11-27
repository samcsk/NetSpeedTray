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
    // Respect card boundaries when the dashboard groups fields into semantic regions.
    // Some layouts render headings and fields as plain siblings under one parent.
    const regions = root.querySelectorAll("article, section, li, [role='group'], [role='region']");
    for (const region of Array.from(regions).reverse()) {
        if (region.checkVisibility()) {
            const balance = readWeeklyCard(region.innerText);
            if (balance) return balance;
        }
    }
    return readWeeklyCard(root.innerText);
}
