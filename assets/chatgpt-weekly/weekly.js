// Match only the two adjacent fields of the English Weekly limit card.
function readWeeklyCard(visibleText) {
    const heading = /^\s*Weekly limit\s*$/im.exec(visibleText);
    if (!heading) return null;
    const card = visibleText.slice(heading.index + heading[0].length).trimStart();
    const duration = "((?:\\d+\\s*[dhm]\\b\\s*){1,3})";
    const reset = "Resets\\s+in\\s+" + duration;
    const percent = "(\\d{1,3})%\\s+left\\b";
    const timeFirst = new RegExp("^" + reset + "\\s*" + percent, "i").exec(card);
    const percentFirst = new RegExp("^" + percent + "\\s+" + reset, "i").exec(card);
    if (!timeFirst && !percentFirst) return null;
    const left = Number(timeFirst ? timeFirst[2] : percentFirst[1]);
    const countdown = timeFirst ? timeFirst[1] : percentFirst[2];
    const units = {d: 1440, h: 60, m: 1};
    let minutes = 0;
    for (const [, amount, unit] of countdown.toLowerCase().matchAll(/(\d+)\s*([dhm])/g)) {
        minutes += Number(amount) * units[unit];
    }
    return left <= 100 && minutes <= 10080 ? {left, minutes} : null;
}
