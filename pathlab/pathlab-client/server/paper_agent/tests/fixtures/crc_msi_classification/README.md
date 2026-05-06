# CRC MSI Classification Synthetic Fixture

This fixture is synthetic and contains no real patient data. It is intended for PathLab paper-generation testing.

## Files

- `conversation.md` / `conversation.json`: simulated short pre-training chat that establishes the topic.
- `idea.md`: paper intent with a `[TOPIC_CONTEXT]` block that can be passed as `CreatePaperRequest.user_idea`.
- `paper_request.json`: example `POST /papers` body.
- `task_record.json`, `trained_model.json`, `wsi_slides.csv`: simulated PathLab experiment metadata.
- `analysis/summary.json`, `analysis/results.json`, `analysis/bootstrap_ci.json`: simulated analysis outputs.
- `analysis/charts/*.png`: simulated PathLab result-analysis charts.
- `raw_collected/collector_bundle.json` and `raw_collected/analysis/`: Phase 02-style raw collector bundle plus staged analysis files; copy the whole `raw_collected/` directory into `uploads/paper_generation/{paper_id}/evidence/raw_collected/` if you want to run Phase 03+ without a real DB task.

## Intended Paper Topic

CRC MSI prediction from H&E whole-slide images using attention-based multiple instance learning.

## Key Synthetic Results

- Cohort: 312 WSIs / 312 cases.
- Classes: 96 MSI, 216 MSS.
- Split: train 188, validation 62, test 62.
- Test AUROC: 0.9413.
- Test accuracy: 0.8871.
- Balanced accuracy: 0.8621.
- Macro F1: 0.8504.
- MSI sensitivity: 0.7895.
- MSS specificity: 0.9302.

## Included Result Charts

- `analysis/charts/roc_curve.png`: test-set MSI-vs-MSS ROC curve.
- `analysis/charts/pr_curve.png`: test-set MSI precision-recall curve.
- `analysis/charts/confusion_matrix.png`: test-set confusion matrix.
- `analysis/charts/calibration.png`: test-set MSI probability calibration.

## Claim Boundary

This fixture does not include external validation, prospective validation, or deployment evidence. Generated manuscripts should avoid those claims.
