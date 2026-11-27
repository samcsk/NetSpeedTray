"""Size and paint the quota panel using the taskbar font and text colour."""
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor


def quota_names(config):
    return tuple(label for label, key in (("Devin", "quota_devin"), ("ChatGPT", "quota_codex"))
                 if config.get(key, False))


def quota_width(fm, names, height):
    if not names:
        return 0
    label = max(fm.horizontalAdvance(name) for name in names)
    value = max(fm.horizontalAdvance(text) for text in ("100% · 23h 59m", "100% · 6d 23h", "Open usage", "No quota"))
    columns = 1 if height >= len(names) * fm.height() else len(names)
    return columns * (8 + label + fm.horizontalAdvance("  ") + value)


def quota_height(line_height, names):
    return len(names) * (2 * line_height + 4)


def split_quota_rect(rect, fm, names, vertical):
    if vertical:
        height = min(rect.height(), quota_height(fm.height(), names))
        base = rect.adjusted(0, 0, 0, -height)
        panel = QRect(rect.left(), base.bottom() + 1, rect.width(), height)
    else:
        width = min(rect.width(), quota_width(fm, names, rect.height()))
        base = rect.adjusted(0, 0, -width, 0)
        panel = QRect(base.right() + 1, rect.top(), width, rect.height())
    return base, panel


def draw_quotas(painter, panel, names, values, vertical, color):
    painter.save()
    try:
        painter.setClipRect(panel, Qt.ClipOperation.IntersectClip)
        painter.setPen(QColor(color))
        fm = painter.fontMetrics()
        stacked = vertical or panel.height() >= len(names) * fm.height()
        width = panel.width() if stacked else panel.width() // len(names)
        height = panel.height() // len(names) if stacked else panel.height()
        for i, name in enumerate(names):
            x = panel.x() if stacked else panel.x() + i * width
            y = panel.y() + i * height if stacked else panel.y()
            value = values.get("codex" if name == "ChatGPT" else name.lower(), "…")
            if vertical:
                half = height // 2
                if fm.horizontalAdvance(value) > width and "%" in value:
                    value = value.split()[0]
                painter.drawText(QRect(x, y, width, half), Qt.AlignmentFlag.AlignCenter, name)
                painter.drawText(QRect(x, y + half, width, height - half), Qt.AlignmentFlag.AlignCenter,
                                 fm.elidedText(value, Qt.TextElideMode.ElideRight, width))
            else:
                painter.drawText(QRect(x + 4, y, width - 8, height),
                                 Qt.AlignmentFlag.AlignCenter, f"{name}  {value}")
    finally:
        painter.restore()
