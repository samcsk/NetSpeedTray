"""Size and paint the quota panel using the taskbar font and text colour."""
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor

from netspeedtray.utils.font_runs import draw_text, first_row_baseline


def quota_names(config):
    return tuple(label for label, key in (("Devin", "quota_devin"), ("ChatGPT", "quota_codex"))
                 if config.get(key, False))


def quota_width(fm, names, height):
    if not names:
        return 0
    label = max(fm.horizontalAdvance(name) for name in names)
    statuses = ("100% 7d", "100% 24h", "100% 60m", "100% <1m",
                "Reinstall", "Sign in", "No quota", "No data", "Set up", "Retry")
    value = max(fm.horizontalAdvance(text) for text in statuses)
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


def draw_quotas(painter, panel, names, values, vertical, color, fm):
    painter.save()
    try:
        painter.setClipRect(panel, Qt.ClipOperation.IntersectClip)
        painter.setPen(QColor(color))
        stacked = vertical or panel.height() >= len(names) * fm.height()
        width = panel.width() if stacked else panel.width() // len(names)
        if vertical:
            height = panel.height() // len(names)
        else:
            baseline = panel.y() + first_row_baseline(fm, panel.height(), len(names) if stacked else 1)
        for i, name in enumerate(names):
            x = panel.x() if stacked else panel.x() + i * width
            value = values.get("codex" if name == "ChatGPT" else name.lower(), "…")
            if vertical:
                y = panel.y() + i * height
                half = height // 2
                if fm.horizontalAdvance(value) > width and "%" in value:
                    value = value.split()[0]
                painter.drawText(QRect(x, y, width, half), Qt.AlignmentFlag.AlignCenter, name)
                painter.drawText(QRect(x, y + half, width, height - half), Qt.AlignmentFlag.AlignCenter,
                                 fm.elidedText(value, Qt.TextElideMode.ElideRight, width))
            else:
                text = f"{name}  {value}"
                text_x = x + (width - fm.horizontalAdvance(text)) // 2
                painter.save()
                try:
                    painter.setClipRect(QRect(x + 4, panel.y(), max(0, width - 8), panel.height()),
                                        Qt.ClipOperation.IntersectClip)
                    draw_text(painter, text_x, baseline, text)
                finally:
                    painter.restore()
                if stacked:
                    baseline += fm.height()
    finally:
        painter.restore()
