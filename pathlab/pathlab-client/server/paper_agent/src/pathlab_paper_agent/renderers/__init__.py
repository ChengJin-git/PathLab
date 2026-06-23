"""Rendering helpers for PathLab paper-generation templates."""

from __future__ import annotations

from typing import Any

from .locked_block_renderer import LockedBlockRenderer, LockedBlockRenderResult

__all__ = [
    "LockedBlockRenderer",
    "LockedBlockRenderResult",
    "export_bundle",
    "render_template",
]


def render_template(*args: Any, **kwargs: Any):
    from .template_renderer import render_template as _render_template

    return _render_template(*args, **kwargs)


def export_bundle(*args: Any, **kwargs: Any):
    from .zip_exporter import export_bundle as _export_bundle

    return _export_bundle(*args, **kwargs)
