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
    "pfm_feature_extractor_benchmark": {
        "id": "pfm_feature_extractor_benchmark",
        "title": "Benchmarking foundation models as feature extractors for weakly-supervised computational pathology",
        "url": "https://www.nature.com/articles/s41551-025-01516-3",
        "path": str(TRAINING_PAPERS_DIR / "pfm_feature_extractor_benchmark.pdf"),
    },
    "clinical_public_pfm_benchmark": {
        "id": "clinical_public_pfm_benchmark",
        "title": "A clinical benchmark of public self-supervised pathology foundation models",
        "url": "https://www.nature.com/articles/s41467-025-58796-1",
        "path": str(TRAINING_PAPERS_DIR / "clinical_public_pfm_benchmark.pdf"),
    },
    "uni": {
        "id": "uni",
        "title": "Towards a General-Purpose Foundation Model for Computational Pathology",
        "url": "https://www.nature.com/articles/s41591-024-02857-3",
        "path": str(TRAINING_PAPERS_DIR / "UNI.pdf"),
    },
    "conch": {
        "id": "conch",
        "title": "A visual-language foundation model for computational pathology",
        "url": "https://www.nature.com/articles/s41591-024-02856-4",
        "path": str(TRAINING_PAPERS_DIR / "CONCH.pdf"),
    },
    "prov_gigapath": {
        "id": "prov_gigapath",
        "title": "A whole-slide foundation model for digital pathology from real-world data",
        "url": "https://www.nature.com/articles/s41586-024-07441-w",
        "path": str(TRAINING_PAPERS_DIR / "Prov-GigaPath.pdf"),
    },
    "virchow": {
        "id": "virchow",
        "title": "A foundation model for clinical-grade computational pathology and rare cancers detection",
        "url": "https://www.nature.com/articles/s41591-024-03141-0",
        "path": str(TRAINING_PAPERS_DIR / "Virchow.pdf"),
    },
    "titan": {
        "id": "titan",
        "title": "A multimodal whole-slide foundation model for pathology",
        "url": "https://www.nature.com/articles/s41591-025-03982-3",
        "path": str(TRAINING_PAPERS_DIR / "TITAN.pdf"),
    },
    "clam": {
        "id": "clam",
        "title": "Data-efficient and weakly supervised computational pathology on whole-slide images",
        "url": "https://www.nature.com/articles/s41551-020-00682-w",
        "path": str(TRAINING_PAPERS_DIR / "CLAM.pdf"),
    },
    "transmil": {
        "id": "transmil",
        "title": "TransMIL: Transformer based Correlated Multiple Instance Learning for Whole Slide Image Classification",
        "url": "https://proceedings.neurips.cc/paper/2021/hash/10c272d06794d3e5785d5e7c5356e9ff-Abstract.html",
        "path": str(TRAINING_PAPERS_DIR / "TransMIL.pdf"),
    },
    "abmil": {
        "id": "abmil",
        "title": "Attention-based Deep Multiple Instance Learning",
        "url": "https://arxiv.org/abs/1802.04712",
        "path": str(TRAINING_PAPERS_DIR / "ABMIL.pdf"),
    },
    "pathosam": {
        "id": "pathosam",
        "title": "PathoSAM: Foundation model for digital pathology segmentation",
        "url": "https://arxiv.org/abs/2502.00408",
        "path": str(TRAINING_PAPERS_DIR / "PathoSAM.pdf"),
    },
    "sam_digital_pathology": {
        "id": "sam_digital_pathology",
        "title": "Zero-shot evaluation of Segment Anything Model for digital pathology",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC11971729/",
        "path": str(TRAINING_PAPERS_DIR / "SAM_Digital_Pathology.pdf"),
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
