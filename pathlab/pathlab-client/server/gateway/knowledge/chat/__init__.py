"""Bundled chat knowledge assets and metadata."""

from __future__ import annotations

from pathlib import Path

CHAT_KNOWLEDGE_DIR = Path(__file__).resolve().parent
FEATURE_EXTRACTOR_META_PATH = CHAT_KNOWLEDGE_DIR / "feature_extractors_meta.json"
TRAINING_PAPERS_DIR = CHAT_KNOWLEDGE_DIR / "papers"
TRAINING_RAG_DIR = CHAT_KNOWLEDGE_DIR / "training_rag"
TRAINING_RAG_CACHE_DIR = TRAINING_RAG_DIR / "cache"
TRAINING_RAG_VECTORSTORE_DIR = TRAINING_RAG_DIR / "vector_store"

BUNDLED_TRAINING_PDF_SOURCES: dict[str, dict[str, str]] = {
    "pathbench": {
        "id": "pathbench",
        "title": "PathBench: A Multi-task, Multi-organ Benchmark for Pathology Foundation Models",
        "url": "https://pathlab.local/training-recommendation/PathBench.pdf",
        "path": str(TRAINING_PAPERS_DIR / "PathBench.pdf"),
    },
    "smart_ccs": {
        "id": "smart_ccs",
        "title": "Generalizable Cervical Cancer Screening via Large-scale Pretraining and Test-Time Adaptation",
        "url": "https://pathlab.local/training-recommendation/Smart-CCS.pdf",
        "path": str(TRAINING_PAPERS_DIR / "Smart-CCS.pdf"),
    },
}


def get_bundled_training_pdf_source_by_url(url: str) -> dict[str, str] | None:
    for source in BUNDLED_TRAINING_PDF_SOURCES.values():
        if source.get("url") == url:
            return source
    return None
