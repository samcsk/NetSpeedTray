// Only the percentage next to the English Weekly limit heading belongs to this card.
function readWeeklyCard(visibleText) {
    const heading = /^\s*Weekly limit\s*$/im.exec(visibleText);
    if (!heading) return null;
    // A neighboring limit can render inline. Stop at its heading before reading a value.
    const rest = visibleText.slice(heading.index + heading[0].length).trimStart();
    const card = rest.split(/\b(?:limits?|quotas?)\b/i, 1)[0];
    // A wrapped duration can span several lines in the card's visible text.
    const fields = card.replace(/^Resets\s+in\s+(?:\d+\s*[dhm]\b\s*)+/i, "");
    const percent = /^(?:Resets?\b[^\r\n%]*?\s+)?(\d{1,3})%\s+left\b/i.exec(fields);
    if (!percent) return null;
    const left = Number(percent[1]);
    return left <= 100 ? {left} : null;
}
