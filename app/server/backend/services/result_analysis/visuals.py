"""Stable class colors shared by result metadata and rendered segmentation masks."""

CLASS_COLORS = (
    "#e11d48",
    "#2563eb",
    "#059669",
    "#d97706",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#65a30d",
    "#9333ea",
    "#475569",
)


def class_color(index):
    return CLASS_COLORS[index % len(CLASS_COLORS)]


def class_colors(classes):
    return [class_color(index) for index, _ in enumerate(classes or [])]
