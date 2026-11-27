// Only the percentage next to the English Weekly limit heading belongs to this card.
function readWeeklyCard(visibleText) {
    const heading = /^\s*Weekly limit\s*$/im.exec(visibleText);
    if (!heading) return null;
    const card = visibleText.slice(heading.index + heading[0].length).trimStart();
    const percent = /^(?:Resets\s+in\s+(?:\d+\s*[dhm]\b\s*){1,3})?(\d{1,3})%\s+left\b/i.exec(card);
    if (!percent) return null;
    const left = Number(percent[1]);
    return left <= 100 ? {left} : null;
}
