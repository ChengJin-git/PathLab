<div align="center">
  <img src="app/src/renderer/public/images/pathlab-logo.png" width="480" alt="PathLab">
</div>

<br>

<div align="center">

[![arXiv](https://img.shields.io/badge/arXiv-2606.20677-b31b1b.svg)](https://arxiv.org/abs/2606.20677)
[![License](https://img.shields.io/badge/License-Academic%20non--commercial-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org)
[![Node](https://img.shields.io/badge/Node-22.22%2B%20%7C%2024.15%2B%20%7C%2026-339933.svg)](https://nodejs.org)

</div>

PathLab is an AI co-scientist for computational pathology. Investigators state a research
question in natural language; PathLab plans the analysis, checks it against the data and study
design before anything runs, builds or reuses models and tools, executes the workflow and returns
inspectable measurements, visualizations and evaluation results.

This repository contains the complete source code of the PathLab web platform described in the
manuscript below. It is a browser/server (B/S) web application: a React client served by nginx
and Python services that run on a Linux GPU server.

## Research paper

**Paper:** [Democratizing and accelerating AI-driven pathology research through agentic
intelligence](https://arxiv.org/abs/2606.20677) (arXiv:2606.20677). Jiabo Ma\*, Cheng Jin\*,
Yihui Wang\*, *et al.*, Li Liang†, Hao Chen†. (\*equal contribution, †corresponding authors)

The abstract below and the code map in this README follow the revised version of the manuscript,
currently under review as *An AI co-scientist for democratizing and accelerating computational
pathology through agentic intelligence*.

A hosted instance is available at [pathlab.cse.ust.hk](https://pathlab.cse.ust.hk). Citation
details are in [CITATION.cff](CITATION.cff) and [Citation](#citation).

### Abstract

Computational pathology plays a pivotal role in precision medicine, yet research in this field
remains concentrated in a few well-resourced interdisciplinary centers. Most pathologists hold the
clinical questions, disease expertise, and real-world cohorts needed for discovery, but lack
dedicated computational teams. Here we present PathLab, an AI co-scientist that works alongside
domain researchers to conduct computational pathology studies from natural-language objectives.
It connects pathology foundation models and analytical tools with pre-execution checks to support
model development, tool adaptation, and hypothesis testing. Before running a workflow, PathLab
checks compatibility with the data and study design to catch errors such as data leakage. Across
100 flawed analytical requests, it intercepted 99 before execution. On 27 datasets spanning eight
task types, workflows produced by PathLab were non-inferior to pipelines built by six experienced
AI researchers. PathLab also adapts existing models and tools to practical pathology problems,
such as turning qualitative morphological observations into inspectable quantitative analyses. In
a 35-participant multicenter study, all 23 pathologists and medical students using PathLab
completed three modeling tasks (versus 10 of 12 coding participants). Both groups matched senior AI
researchers in mean area under the receiver operating characteristic curve (0.872 for
pathologists and 0.878 for medical students, versus 0.878 for senior AI researchers and 0.820 for
junior AI students), and pathologists completed the tasks in 17.6% less time on average (7.01 h
versus 8.51 h). Finally, we tested whether PathLab could generate and validate hypotheses on tumor
regression grade in colorectal cancer across 902 patients from three centers. Starting from
patch-level tissue compartment maps without prespecified spatial metrics or statistical tests,
PathLab proposed ten topological hypotheses prior to outcome inspection and evaluated them
unchanged in two independent external cohorts. The analysis reproduced known regression patterns
and identified the fraction of cancer retained in the largest connected component as a spatial
correlate of tumor regression grade across all three centers. Together, these findings show how
computational research can move beyond specialized centers to studies led directly by domain
experts with an AI co-scientist.

## About this repository

This is the public, self-contained edition of PathLab: everything needed to run the platform on
your own server.

**Included**

- The full web platform: data management, whole-slide viewer and annotation, model training and
  inference, result analysis, chat workspace, autonomous research sessions and article writing.
- The research controller, its skill interface, the pre-execution methodological checks and the
  sandboxed execution environment described in the Methods.
- Integrations for 20 pathology foundation models and general encoders, multiple-instance learning
  aggregators, segmentation and detection models (code only; see below for weights).
- Multi-user accounts with administrator, pathologist and guest roles.
- Deployment scripts, nginx/systemd templates, the research-sandbox image recipe and the test
  suites (about 1,900 backend and 1,100 frontend tests).

**Not included**

- **Model weights.** Foundation-model checkpoints are downloaded from their original publishers
  (most require accepting a license on Hugging Face and an access token).
- **Datasets.** The 27 public benchmark datasets are available from their original sources
  (Supplementary Table S3 of the manuscript). The clinical cohorts used in the user study and the
  multicenter discovery study are not public; see *Data Availability* in the manuscript.
- **Evaluation materials.** The adversarial prompt suite, prompt-stability suite and task
  descriptions used in the evaluations are listed in the manuscript's Supplementary Materials.
  This repository is the system that was evaluated; it does not contain the evaluation runs.
- **LLM access.** PathLab calls a language model you configure (any OpenAI-compatible endpoint,
  including self-hosted vLLM). No API keys are shipped.
- **Billing and hosted-service features** (payments, e-mail notifications, maintenance
  announcements, per-user dataset grants). The hosted instance runs a separately maintained
  service edition; the research functionality is the same.

## How the code maps to the paper

| Paper (Methods, Fig. 7) | What it is | Where it lives |
| --- | --- | --- |
| Research controller | LLM-based controller that interprets the objective and chooses the next action. Runs as an OpenCode agent for research sessions and as the chat assistant for interactive work. | [`app/server/backend/autoresearch/engine/`](app/server/backend/autoresearch/engine), [`app/server/gateway/routes/chat.py`](app/server/gateway/routes/chat.py), [`app/server/gateway/chat/`](app/server/gateway/chat) |
| Auto-pilot / Co-pilot | Research sessions run autonomously with plans, follow-up instructions and pause/resume; in chat, the investigator reviews and edits each proposed configuration before submitting it. Both use the same controller and checks. | [`app/src/renderer/src/pages/AutoResearch*`](app/src/renderer/src/pages), [`app/src/renderer/src/pages/AIChatPage.tsx`](app/src/renderer/src/pages/AIChatPage.tsx) |
| Skill interface (tools and skills) | Built-in skills, imported skill packages and connectors the controller can load on demand. | [`engine/skills.py`](app/server/backend/autoresearch/engine/skills.py), [`engine/builtin_skills.py`](app/server/backend/autoresearch/engine/builtin_skills.py), [`engine/tools.py`](app/server/backend/autoresearch/engine/tools.py), [`skill_library/`](app/server/backend/autoresearch/skill_library), [`services/capability_library.py`](app/server/backend/services/capability_library.py) |
| Built-in foundation-model integrations | Patch encoders (UNI, UNI2, CONCH, CONCH v1.5, Virchow, Virchow2, H-Optimus, GPFM, Phikon, PLIP, mSTAR, KRONOS, …), MIL aggregators, classifiers, segmentation and detection models, and the trainers for the five built-in task types. | [`app/server/backend/ai/`](app/server/backend/ai) |
| Apply / Develop / Discover | Apply: built-in training, inference and analysis cards. Develop: sandboxed code generation and experiments. Discover: evidence-backed study decisions, literature and dataset retrieval. | [`app/server/gateway/prompts/`](app/server/gateway/prompts), [`engine/jobs.py`](app/server/backend/autoresearch/engine/jobs.py), [`engine/study.py`](app/server/backend/autoresearch/engine/study.py), [`autoresearch/literature/`](app/server/backend/autoresearch/literature), [`autoresearch/dataset/`](app/server/backend/autoresearch/dataset) |
| Pre-execution methodological checks | Encoded rules given to the controller (task–data compatibility, split and evaluation requirements, no fabricated results) and server-side validation that runs regardless of the model's output: task taxonomy, dataset/task compatibility, label and annotation checks, patient-level splitting, external-validation compatibility and research study contracts. | [`gateway/prompts/workflows.py`](app/server/gateway/prompts/workflows.py), [`gateway/prompts/execution.py`](app/server/gateway/prompts/execution.py), [`ai/task_taxonomy.py`](app/server/backend/ai/task_taxonomy.py), [`services/dataset_catalog.py`](app/server/backend/services/dataset_catalog.py), [`ai/utils/data_splitter.py`](app/server/backend/ai/utils/data_splitter.py), [`routes/external_validation_analysis.py`](app/server/gateway/routes/external_validation_analysis.py), [`engine/study_contract.py`](app/server/backend/autoresearch/engine/study_contract.py) |
| Execution environment | GPU task queue and workers for built-in tasks; Apptainer (or Docker) sandbox for generated code and experiments. | [`app/server/task_worker/`](app/server/task_worker), [`engine/runtime.py`](app/server/backend/autoresearch/engine/runtime.py), [`autoresearch/runtime/containers/`](app/server/backend/autoresearch/runtime/containers) |
| Inspectable outputs | Measurements, result layers in the viewer, statistical analysis, reports and articles with verified citations. | [`app/server/backend/services/result_analysis/`](app/server/backend/services/result_analysis), [`services/REPORTS.md`](app/server/backend/services/REPORTS.md), [`app/src/renderer/src/components/wsiViewer/`](app/src/renderer/src/components/wsiViewer) |
| Reusable assets (retain) | Models, features, tools and workflows produced during a study are registered for later discovery and reuse. | [`engine/registration.py`](app/server/backend/autoresearch/engine/registration.py), [`services/FEATURE-ARTIFACTS.md`](app/server/backend/services/FEATURE-ARTIFACTS.md), [`services/capability_library.py`](app/server/backend/services/capability_library.py) |

A longer walkthrough is in [docs/architecture.md](docs/architecture.md).

## Quick start

### Prerequisites

- Linux x86_64 (Ubuntu 22.04 or 24.04 tested) with an NVIDIA GPU and a driver compatible with
  CUDA 13 (PyTorch 2.12). CPU-only servers run the web platform but not GPU training.
- Python 3.12 or newer, Node.js 22.22.2+, 24.15+ or 26.x, PostgreSQL, Redis.
- [Apptainer](https://apptainer.org) for the research sandbox (Docker is also supported).
- An LLM endpoint: an API key for an OpenAI-compatible service (OpenAI, OpenRouter, …) or a
  self-hosted vLLM server.
- A Hugging Face access token if you want to use gated foundation models.

### 1. Get the code and system packages

```bash
git clone https://github.com/ChengJin-git/PathLab.git
cd PathLab/app
sudo bash deploy/install-system-deps.sh   # PostgreSQL, Redis, OpenSlide, Apptainer, LibreOffice
npm ci                                     # web client dependencies
```

### 2. Install the Python services

```bash
python3.12 -m venv ~/.local/share/PathLab/venv
source ~/.local/share/PathLab/venv/bin/activate
pip install -r server/requirements.txt
python deploy/verify-runtime.py            # imports and small compute checks
python deploy/prepare-knowledge.py         # embedding model for literature retrieval
python deploy/prepare-ocr.py               # OCR model for scanned PDFs
python deploy/install-opencode.py --output ~/.opencode/bin/opencode
```

### 3. Configure

```bash
sudo -u postgres createuser --pwprompt pathlab
sudo -u postgres createdb --owner=pathlab pathlab
cp server/.env.example server/.env
```

Edit `server/.env`: set `DATABASE_URL`, `REDIS_URL`, a random `JWT_SECRET`
(`openssl rand -hex 32`) and `DEFAULT_ADMIN_PASSWORD`. If you leave the admin password empty, a
random one is printed once in the server log on first start. All variables are described in
[docs/configuration.md](docs/configuration.md).

### 4. Build the research sandbox

```bash
python deploy/build-skills-runtime.py --rebuild-base
```

This builds the Apptainer image used for autonomous research from the recipes in
`server/backend/autoresearch/runtime/containers/`. It takes a while and needs network access.
See [docs/installation.md](docs/installation.md#research-sandbox) for Docker and offline options.

### 5. Start and sign in

```bash
export PATHLAB_PYTHON=$(which python)
bash deploy/start.sh
curl -f http://127.0.0.1:6100/health
```

`start.sh` builds the web client and starts three HTTP services (Gateway 6100, Preprocessing 6101,
AI 6102) and two workers (TaskWorker, ResearchWorker). Put nginx in front using
[`deploy/nginx/pathlab.conf`](app/deploy/nginx/pathlab.conf), open the site, sign in as `admin` and
configure the language model under **Settings → General**.

The full guide, including nginx, systemd, GPU selection, storage locations and upgrades, is in
[docs/installation.md](docs/installation.md).

## Using PathLab

1. **Register data** under *Data* (`/datasets`, `/upload`): whole-slide images or patches, with
   labels from CSV or COCO files. Datasets can carry several tasks at once.
2. **Ask in Chat.** Describe the study; PathLab proposes a configuration card (dataset, task,
   encoder, aggregator, splits). Review and edit it, then submit. Results, metrics and heatmaps
   come back to the conversation.
3. **Run a research session** for open-ended work: PathLab plans, writes and runs code in the
   sandbox, records decisions and evidence, and asks you when it needs a choice.
4. **Inspect results** in the whole-slide viewer (result layers, attention, annotations), in the
   analysis pages and in generated reports.

## Repository structure

```text
PathLab/
├── app/
│   ├── src/renderer/      # React + TypeScript web client (Vite)
│   ├── server/
│   │   ├── main.py        # starts Gateway, Preprocessing, AI, TaskWorker and ResearchWorker
│   │   ├── gateway/       # public API, chat workspace, prompts and workflow contracts
│   │   ├── backend/
│   │   │   ├── ai/            # foundation models, aggregators, trainers, inference
│   │   │   ├── autoresearch/  # research controller runtime, skills, literature, datasets, sandbox
│   │   │   ├── preprocessing/ # whole-slide reading, tiling, thumbnails
│   │   │   ├── services/      # datasets, viewer, features, reports, file library
│   │   │   ├── database/      # SQLAlchemy models and schema
│   │   │   └── auth/          # accounts and roles
│   │   ├── task_worker/   # GPU task queue
│   │   └── tests/         # backend tests (pytest)
│   ├── test/              # frontend tests (Vitest)
│   └── deploy/            # install, start, nginx, systemd, sandbox build
├── docs/                  # installation, configuration, architecture, reproducibility
├── LICENSE
└── CITATION.cff
```

## Documentation

- [Installation](docs/installation.md) · [Configuration](docs/configuration.md) ·
  [Architecture and code map](docs/architecture.md) · [Reproducibility and data](docs/reproducibility.md)
- Developer notes: [web client](app/README.md), [backend](app/server/README.md),
  [research runtime](app/server/backend/autoresearch/README.md),
  [chat workspace](app/server/gateway/chat/README.md),
  [permissions](app/server/permissions/README.md), [tests](app/test/README.md)

## Citation

If you use PathLab, please cite:

```bibtex
@article{ma2026pathlab,
  title   = {Democratizing and accelerating AI-driven pathology research through agentic intelligence},
  author  = {Ma, Jiabo and Jin, Cheng and Wang, Yihui and Jiang, Hao and Liang, Ling and Xu, Yingxue and
             Hou, Junlin and Guo, Zhengrui and Zhang, Zhengyu and Xia, Yifei and Wang, Hongyi and
             Zhou, Fengtao and Xu, Zhe and Zhou, Huajun and Ouyang, Jiarui and Zeng, Qian and
             Tang, On Ki and Park, Eunhyang and Glass, Carolyn and Chan, Ronald Cheong Kin and
             Liang, Li and Chen, Hao},
  journal = {arXiv preprint arXiv:2606.20677},
  year    = {2026},
  url     = {https://arxiv.org/abs/2606.20677}
}
```

## License

PathLab is released for academic, non-commercial use under the terms in [LICENSE](LICENSE).
For commercial licensing, contact Prof. Hao Chen (jhc@ust.hk). Third-party components keep their
own licenses; model weights are subject to the terms of their publishers.

PathLab is a research tool. It is not a medical device and must not be used for clinical
diagnosis or treatment decisions.

## Acknowledgements

This work was supported by the Hong Kong Innovation and Technology Commission (PRP/086/24FX,
GHP/006/22GD, ITC-SKLNSD26SC01) and the Research Grants Council of the Hong Kong SAR (R6003-22,
JLFS/M-604/24). PathLab builds on many open-source projects, including OpenCode, OpenSlide,
PyTorch, timm, segmentation_models.pytorch and the authors of the foundation models it integrates.
