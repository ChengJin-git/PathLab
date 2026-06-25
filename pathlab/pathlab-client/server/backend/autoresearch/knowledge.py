"""Domain knowledge as SDK Skills — auto-injected via keyword triggers.

Uses OpenHands SDK AgentContext + Skill + KeywordTrigger system.
When user message contains matching keywords, relevant knowledge
is automatically injected into the LLM context as <EXTRA_INFO>.
"""
from __future__ import annotations

from openhands.sdk.context.skills.skill import Skill
from openhands.sdk.context.skills.trigger import KeywordTrigger


# --- MIL Classification ---

MIL_CLASSIFICATION_KNOWLEDGE = Skill(
    name="mil-classification",
    content="""\
# MIL Classification — Domain Knowledge

## Key Methods
- **ABMIL** (Ilse 2018): Gated attention pooling over patch embeddings → slide logits. Simple, strong baseline.
- **CLAM** (Lu 2021): Clustering-constrained attention. Instance-level + bag-level supervision. Single/multi-branch.
- **TransMIL** (Shao 2021): Transformer with PPEG for position encoding. Captures long-range morphological correlations.
- **DSMIL** (Li 2021): Dual-stream with max-pooling + attention. Critical instance + context instance branches.
- **DTFD-MIL** (Zhang 2022): Double-tier feature distillation. Pseudo-bag augmentation for small datasets.

## Feature Extractors (Frozen, Pre-trained)
| Extractor | Dim | Notes |
|-----------|-----|-------|
| UNI (Chen 2024) | 1024 | ViT-L, pathology foundation model |
| UNI2 | 1536 | Improved UNI |
| CONCH (Lu 2024) | 512 | Vision-language, pathology-specific |
| CONCH 1.5 | 512 | Updated CONCH |
| Virchow (Vorontsov 2024) | 1280 | DINOv2-based, large-scale pretraining |
| Virchow2 | 1280 | Improved Virchow |
| Phikon (Filiot 2023) | 1024 | ViT-B, iBOT self-supervised |
| H-Optimus-0 | 1536 | Bioptimus foundation model |
| ResNet50 (ImageNet) | 2048 | Legacy baseline |

## Best Practices
- **Optimizer**: Adam or AdamW with lr=1e-4 to 2e-4, weight_decay=1e-5
- **Scheduler**: Cosine annealing with warm restarts (T_0=10-20 epochs)
- **Class imbalance**: Compute class weights from label distribution, apply to CrossEntropyLoss
- **Evaluation**: AUC (primary), accuracy, F1, precision, recall on test split
- **Batch size**: Always 1 (one WSI bag per step) — do NOT use DataLoader batching
- **Early stopping**: Monitor val_loss with patience=10-15 epochs
- **Augmentation**: Feature-level dropout (p=0.1-0.25) on patch embeddings

## Common Pitfalls
- Feature dim mismatch: extractor output dim must match model input dim
- Forgetting .cuda() on model or data tensors
- Using DataLoader batch_size > 1 (WSI bags have variable num_patches)
- Not setting random seeds for reproducibility
""",
    trigger=KeywordTrigger(keywords=[
        "classification", "MIL", "ABMIL", "CLAM", "TransMIL", "DSMIL",
        "WSI", "slide", "attention pooling", "aggregator",
    ]),
)

# --- Survival Analysis ---

SURVIVAL_ANALYSIS_KNOWLEDGE = Skill(
    name="survival-analysis",
    content="""\
# Survival Analysis — Domain Knowledge

## Key Methods
- **DeepSurv** (Katzman 2018): Cox proportional hazards with neural network. Simple, interpretable.
- **ABMIL + Cox**: Attention-based MIL with Cox partial likelihood loss.
- **Patch-GCN** (Chen 2021): Graph neural network on WSI patches for survival prediction.
- **TransMIL + NLL**: Transformer MIL with discrete-time survival (NLL-MTLR loss).

## Loss Functions
- **Cox Partial Likelihood**: Standard for continuous-time survival. Rank-based, handles censoring.
- **NLL-MTLR** (Multi-Task Logistic Regression): Discrete-time. Bins time into intervals, predicts hazard per bin.
- **Ranking Loss**: DeepHit-style, pairwise ranking of survival times.

## Evaluation Metrics
- **C-index** (concordance index): Primary metric. Probability that model correctly ranks two patients.
- **Time-dependent AUC**: AUC at specific time points.
- **Brier Score**: Calibration metric.

## Best Practices
- Handle censored data properly (censoring indicator in loss, not just labels)
- Use stratified splits to maintain event rate across train/val/test
- C-index > 0.65 is meaningful for most pathology survival tasks
- Typically fewer epochs needed than classification (20-50 vs 50-100)
""",
    trigger=KeywordTrigger(keywords=[
        "survival", "cox", "hazard", "censoring", "c-index",
        "prognosis", "time-to-event", "DeepSurv",
    ]),
)

# --- Feature Extraction ---

FEATURE_EXTRACTION_KNOWLEDGE = Skill(
    name="feature-extraction",
    content="""\
# Feature Extraction — Domain Knowledge

## Pipeline
1. WSI → Tiling (256x256 or 512x512 patches at 20x magnification)
2. Patches → Feature extractor (frozen pre-trained model)
3. Per-patch features → Concatenate → (N_patches, D) tensor per WSI
4. Save as .pt files for downstream MIL tasks

## Key Extractors
- **UNI**: Best overall for pathology. ViT-L/16, 1024-dim.
- **CONCH**: Vision-language model. 512-dim. Good for zero-shot.
- **Virchow**: DINOv2-G/14. 1280-dim. Large model, high quality.
- **Phikon**: ViT-B/16, iBOT. 1024-dim. Lightweight option.

## Best Practices
- Use 20x magnification (0.5 μm/px) as default
- Tissue detection: Otsu thresholding on grayscale, discard background patches
- Normalize: ImageNet mean/std for ImageNet-pretrained, model-specific for pathology models
- Batch size: 64-256 patches per GPU batch (patches, not WSIs)
- Save features as fp16 to reduce storage (minimal quality impact)
- Coordinate extraction: Save (x, y) coords alongside features for spatial analysis
""",
    trigger=KeywordTrigger(keywords=[
        "feature extraction", "extract features", "tiling", "patches",
        "embeddings", "foundation model", "pre-trained",
    ]),
)

# --- General Pathology ---

PATHOLOGY_GENERAL_KNOWLEDGE = Skill(
    name="pathology-general",
    content="""\
# Computational Pathology — General Knowledge

## Data Formats
- **WSI** (Whole Slide Image): .svs, .ndpi, .tiff. Gigapixel images (50k-100k px).
- **Features**: Pre-extracted patch embeddings as .pt tensors (N_patches, D).
- **Splits**: JSON with train/val/test lists + labels dict.

## Common Datasets
- **TCGA**: Large-scale multi-cancer. Public. ~11k slides.
- **BRACS**: Breast cancer ROIs. 7 classes. ~500 WSIs.
- **Camelyon16/17**: Lymph node metastasis detection. Binary.
- **PANDA**: Prostate cancer grading. 6 grades.

## Evaluation Standards
- Always report AUC, accuracy, F1 on held-out test set
- Use 5-fold cross-validation when dataset is small (<200 WSIs)
- Report mean ± std across folds
- Compare against at least one published baseline
""",
    trigger=KeywordTrigger(keywords=[
        "pathology", "histology", "WSI", "whole slide",
        "TCGA", "BRACS", "Camelyon", "cancer",
    ]),
)


def build_domain_skills() -> list[Skill]:
    """Return all domain knowledge skills for AutoResearch."""
    return [
        MIL_CLASSIFICATION_KNOWLEDGE,
        SURVIVAL_ANALYSIS_KNOWLEDGE,
        FEATURE_EXTRACTION_KNOWLEDGE,
        PATHOLOGY_GENERAL_KNOWLEDGE,
    ]
