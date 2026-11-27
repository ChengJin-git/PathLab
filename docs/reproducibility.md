# Reproducibility, data and models

This page explains what is needed to repeat the analyses described in the manuscript with this
repository, and what is outside it.

## What this repository provides

- The PathLab platform that was evaluated: research controller, skill interface, pre-execution
  checks, model integrations, trainers, sandboxed execution and analysis code.
- Pinned dependencies: Python packages in `app/server/requirements.txt` (exact versions, GitHub
  dependencies at fixed commits), npm packages in `app/package-lock.json`, the research sandbox
  recipe in `app/server/backend/autoresearch/runtime/containers/`, the agent runtime version in
  `app/package.json` (`opencodeVersion`) and third-party skills with file hashes in
  `app/server/backend/autoresearch/skill_library/sources.lock.json`.
- Tests: about 1,900 backend tests (`app/server/tests/`, `app/server/backend/autoresearch/tests/`)
  and 1,100 frontend tests (`app/test/`).

## Language models

PathLab's controller is model-agnostic. The manuscript lists the backend used for each study
(Methods, *LLM backends*). To repeat a study, configure an endpoint that serves the same model in
**Settings → General**. Results from language-model-driven workflows can vary between runs and model
versions; the manuscript's evaluations report the settings and repetitions used.

## Foundation-model weights

PathLab does not redistribute model checkpoints. On first use, each encoder downloads its weights
from the original publisher using the Hugging Face token configured by the administrator. Many
pathology foundation models are gated: accept their terms on Hugging Face with the same account
first. Weights are cached in `<storage>/extractor_checkpoints/`.

## Datasets

- **Public benchmarks.** The 27 datasets used for the cross-task benchmark are public; access links
  are in Supplementary Table S3 of the manuscript. Register them in PathLab through *Data → Upload*
  (images plus a CSV or COCO label file), or let a research session download supported public
  datasets (Kaggle and NCI GDC need user credentials, see [configuration.md](configuration.md)).
- **Clinical cohorts.** The external user-study cohorts (Nanfang-NSCLC, PWH-GC-IM) and the
  multicenter colorectal-cancer tumor-regression-grade cohort are not public because of patient
  privacy regulations. De-identified data may be requested from the corresponding author for
  academic, non-commercial research, subject to data-use agreements and ethics approval (see *Data
  Availability* in the manuscript).

## Evaluation materials

The adversarial request suite (100 requests in five categories), the prompt-stability suite and
the user-study task descriptions are provided in the manuscript's Supplementary Materials. To run
them, submit the requests in PathLab's chat with the corresponding datasets registered. The
repository does not contain the logs, outputs or statistical analysis scripts of the evaluations.

## Hardware

The evaluations in the manuscript were run on Linux servers with NVIDIA GPUs. Feature extraction
with large foundation models and training need a CUDA GPU; the web platform, viewer and chat do not.

## Reporting problems

Please open an issue on GitHub with the PathLab commit, the steps to reproduce, and the relevant
part of `app/logs/backend.log` (remove any patient information first).
