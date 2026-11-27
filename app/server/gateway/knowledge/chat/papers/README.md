# Training-recommendation papers (optional)

When users ask which feature extractor or aggregator to train with, the chat
assistant cites the papers listed in `gateway/knowledge/chat/__init__.py`
(`BUNDLED_TRAINING_PDF_SOURCES`). The PDFs are not distributed with PathLab
because most are under publisher copyright.

Without them the assistant still gives its built-in recommendations, but
without passage-level citations. To enable citations, download the papers you
are licensed to use and place them here (or in the directory named by
`PATHLAB_KNOWLEDGE_PAPERS_DIR`) under the file names below. They are indexed at
the next server start.

| File name | Paper |
| --- | --- |
| `PathBench.pdf` | PathBench: A Multi-task, Multi-organ Benchmark for Pathology Foundation Models |
| `pfm_feature_extractor_benchmark.pdf` | Benchmarking foundation models as feature extractors for weakly-supervised computational pathology (Nat. Biomed. Eng. 2025) |
| `clinical_public_pfm_benchmark.pdf` | A clinical benchmark of public self-supervised pathology foundation models (Nat. Commun. 2025) |
| `UNI.pdf` | Towards a general-purpose foundation model for computational pathology (Nat. Med. 2024) |
| `CONCH.pdf` | A visual-language foundation model for computational pathology (Nat. Med. 2024) |
| `Prov-GigaPath.pdf` | A whole-slide foundation model for digital pathology from real-world data (Nature 2024) |
| `Virchow.pdf` | A foundation model for clinical-grade computational pathology and rare cancers detection (Nat. Med. 2024) |
| `TITAN.pdf` | A multimodal whole-slide foundation model for pathology (Nat. Med. 2025) |
| `CLAM.pdf` | Data-efficient and weakly supervised computational pathology on whole-slide images (Nat. Biomed. Eng. 2021) |
| `TransMIL.pdf` | TransMIL: Transformer based correlated multiple instance learning for WSI classification (NeurIPS 2021) |
| `ABMIL.pdf` | Attention-based deep multiple instance learning (ICML 2018, arXiv:1802.04712) |
| `PathoSAM.pdf` | PathoSAM: Foundation model for digital pathology segmentation (arXiv:2502.00408) |
| `SAM_Digital_Pathology.pdf` | Zero-shot evaluation of Segment Anything Model for digital pathology (PMC11971729) |
| `Smart-CCS.pdf` | Generalizable cervical cancer screening via large-scale pretraining and test-time adaptation |
