"""Document parsers — extract text from local files for corpus ingestion."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parser_for_path(path: Path) -> DocumentParser:
    """Select the appropriate parser for a file path."""
    suffix = Path(path).suffix.lower()
    if suffix in (".txt", ".md", ".rst"):
        return TextParser()
    if suffix == ".pdf":
        return PdfParser()
    return TextParser()  # fallback


class DocumentParser:
    """Base parser interface."""

    def parse(self, path: Path) -> tuple[str, dict[str, Any]]:
        """Parse a document file. Returns (text, metadata)."""
        raise NotImplementedError


class TextParser(DocumentParser):
    """Plain text / markdown parser."""

    def parse(self, path: Path) -> tuple[str, dict[str, Any]]:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return text, {"format": "text", "path": str(path)}


class PdfParser(DocumentParser):
    """PDF parser with pypdf fallback."""

    def parse(self, path: Path) -> tuple[str, dict[str, Any]]:
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append((i + 1, text))
            full_text = "\n\n".join(text for _, text in pages)
            return full_text, {
                "format": "pdf",
                "path": str(path),
                "page_count": len(reader.pages),
                "pages": [p for p, _ in pages],
                "page_texts": pages,  # [(page_num, text), ...] for page-aware chunking
            }
        except ImportError:
            logger.warning("pypdf not available, reading PDF as raw text")
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            return text, {"format": "pdf_raw", "path": str(path)}
        except Exception as e:
            logger.warning(f"PDF parsing failed for {path}: {e}")
            return "", {"format": "pdf_error", "path": str(path), "error": str(e)}
