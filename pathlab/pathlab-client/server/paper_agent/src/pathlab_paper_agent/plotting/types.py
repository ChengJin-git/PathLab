"""Shared plotting datatypes."""

from __future__ import annotations

from dataclasses import dataclass


class FigureGenerationError(ValueError):
    """Raised when a deterministic figure cannot be backed by evidence."""


@dataclass(frozen=True)
class FigureOutput:
    """Result returned by deterministic figure generators."""

    figure_id: str
    path: str
    status: str
    source: str
    generator: str
    caption: str
    content_type: str = "image/png"

    def to_manifest_entry(self) -> dict[str, str]:
        return {
            "figure_id": self.figure_id,
            "path": self.path,
            "status": self.status,
            "source": self.source,
            "generator": self.generator,
            "caption": self.caption,
            "content_type": self.content_type,
        }
