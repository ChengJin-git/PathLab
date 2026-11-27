# Scientific skills runtime and credentials

> PathLab v1.0.8 · Updated 2026-11-06

## Image contents

The `skills-runtime.def` recipe extends the ML image with:

- Python PDF/image/document tooling: PyMuPDF, pdfplumber, pypdf, pypdfium2,
  python-docx, python-pptx, mammoth, latex2mathml, md-to-word-docx, image2ppt;
- scientific plotting: matplotlib, seaborn, Liberation Sans and CJK fonts;
- COCO RLE mask decoding/encoding via pycocotools;
- R: ggplot2, patchwork, ComplexHeatmap, circlize, svglite, ragg and pdftools;
- Node 22, PptxGenJS, Mermaid CLI, Puppeteer; Playwright and Chromium;
- Pandoc, LibreOffice headless, Poppler, XeLaTeX, Ghostscript and Tesseract;
- upstream academic-search Python dependencies, including MCP and pybliometrics.

Build the image as described below; to move a verified image to another server see the
[migration guide](../../../../../deploy/guides/MIGRATION.md).

The Docker backend uses the separate OCI recipe
[`deploy/sandbox/Dockerfile`](../../../../../deploy/sandbox/Dockerfile), with OpenCode 2.4.2.

Both image recipes use `ml-runtime-requirements.txt` for exact shared ML pins and
`skills-runtime-requirements.txt` for exact helper pins. Torch remains pinned by
each base image. The Docker CPU image is tagged `pathlab/sandbox:1.0.8-r3-cpu`; see the
[dependency baseline](../../../../../deploy/guides/DEPENDENCIES.md) for compatibility decisions.
Its scientific and document toolset is smaller than this complete SIF.

Use `pathlab-mermaid -i figure.mmd -o figure.svg` for the preconfigured Chromium
renderer. Python Playwright uses the installed browser automatically. `image2ppt`
and `md-to-word` are on PATH. Scripts which write beside their inputs should be
copied to a workspace first; the installed skill library is read-only.

The image records exact installed versions in `/opt/pathlab/skills-python-freeze.txt`
and `/opt/pathlab/skills-system-packages.txt`. `/opt/pathlab/ml-constraints.txt`
preserves the original trained-model runtime packages during the extension.
`verify-skills-runtime.py` exercises real document writing/rendering, R/Python
figures, XeLaTeX, Chromium and Mermaid and removes its temporary outputs.

The base predictor uses sklearn 1.9.0 for persisted research models. If a new
survival experiment needs `sksurv`, use the session `install_dependencies` tool with
`numpy==1.26.4`, `scikit-learn==1.7.2`, `scikit-survival==0.26.0` and imports
`sksurv.metrics`, `sklearn`; it installs into that session's venv. The equivalent
requirements are in `server/requirements-sandbox-survival.txt`. Host survival metrics
already use that compatible pair. Do not change the base predictor environment to
install experiment-specific dependencies.

## Credentials

Normal manuscript generation and Humanizer use the model already configured in
PathLab **Settings**. Local figures, R, document conversion, browser automation,
Europe PMC/Crossref retrieval and Humanizer need no additional service key.

Optional skill credentials live outside code and experiment snapshots:

```text
<autoresearch storage>/credentials/        # directory mode 700
├── skills.env                            # mode 600
└── lit-dl/                               # mode 700
    ├── credentials.json                  # mode 600
    └── settings.json                     # mode 600
```

Resolve the root from `Config.get_autoresearch_dir()`; the default is below the configured uploads root.
Copy `deploy/research-skills.env.example` to `skills.env` and fill only the services
you need. The backend reads it for each new agent/computation process; no restart is
needed after editing values. An already-running process keeps its initial values.
Only the documented allowlist is forwarded through Apptainer's clean environment.
Values are not included in OpenCode config, execution manifests or report metadata.
These are operator-managed shared service credentials for authorized research jobs.

| Capability | Configuration | Obtain from |
| --- | --- | --- |
| PubMed direct API contact / higher rate | `PUBMED_EMAIL`, optional `NCBI_API_KEY` | https://www.ncbi.nlm.nih.gov/account/settings/ |
| Unpaywall open-access discovery | `UNPAYWALL_EMAIL` (contact email, no key) | https://unpaywall.org/products/api |
| Image2PPT remote PaddleOCR | `PADDLE_OCR_TOKEN` (AI Studio Access Token) | https://aistudio.baidu.com/account/accessToken |
| Optional image generation | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `IMAGE2PPT_IMAGE_MODEL`, `IMAGE2PPT_IMAGE_BACKEND` | Your OpenAI-Images-compatible service; https://platform.openai.com/api-keys for OpenAI |
| Elsevier full text | `lit-dl/credentials.json`: `elsevier.api_key`, optional `insttoken` / `authtoken` | https://dev.elsevier.com/ |
| Springer Nature metadata/OA/full text | `springer_nature.metadata_api_key`, `openaccess_api_key`, `fulltext_api_key` (distinct service grants) | https://dev.springernature.com/ |
| IEEE | `ieee.api_key`, optional issued `fulltext_endpoint` | https://developer.ieee.org/ |
| Optional Google Scholar discovery | `PATHLAB_SERPAPI_KEY` in backend `.env`, restart backend | https://serpapi.com/ |
| Gated pretrained encoders | Hugging Face token in PathLab Settings, model access approval | https://huggingface.co/settings/tokens |

Configure publisher keys with the bundled script on the host; it prompts without
echoing the key and saves JSON in the upstream format:

```bash
# Run from app/
export LIT_DL_CONFIG_DIR=/path/to/uploads/autoresearch/credentials/lit-dl
python server/backend/autoresearch/skill_library/nature-skills/skills/nature-downloader/scripts/configure_credentials.py set elsevier
python server/backend/autoresearch/skill_library/nature-skills/skills/nature-downloader/scripts/configure_credentials.py set springer_nature --service openaccess
python server/backend/autoresearch/skill_library/nature-skills/skills/nature-downloader/scripts/configure_credentials.py set ieee
```

The downloader credential directory is mounted read-only in agents and jobs at
`/opt/pathlab/lit-dl`; `LIT_DL_CONFIG_DIR` is set automatically. Configure publisher
grants on the host rather than editing the mounted files from an experiment.

Scopus/ScienceDirect in the upstream standalone academic-search MCP uses
pybliometrics' own `~/.config/pybliometrics.cfg`, not the downloader JSON. Its Python
dependencies are installed; that optional MCP service is not enabled automatically.
If configured later, provide the Elsevier key and any institution token in its
service-specific config. The existing PathLab citation MCP remains available.

Institutional full text requires the corresponding subscription and login/session;
an API key does not establish access to every article. Zotero library management
requires a separately configured Zotero MCP/server and its library ID/key. No Zotero
service, institution login, or third-party account is created by this image build.

## Rebuild

From `app/`, build and verify a candidate, then atomically replace the active image. The build
helper removes its staging directory and test outputs:

```bash
"$PATHLAB_PYTHON" deploy/build-skills-runtime.py
```

Images default to `${XDG_DATA_HOME:-$HOME/.local/share}/PathLab/sandbox/pathlab-sandbox.sif`,
outside the source checkout. The helper creates a new ML base when no image exists;
use `--rebuild-base` to rebuild both layers. Candidate images and temporary files stay
beside the persistent target, and only a verified candidate replaces it.

For a manual candidate build:

```bash
apptainer build --fakeroot --mksquashfs-args '-processors 4 -comp zstd -Xcompression-level 3' \
  --build-arg base_image="$HOME/.local/share/PathLab/sandbox/pathlab-sandbox.sif" \
  --build-arg repo_root="$PWD" \
  "$HOME/.local/share/PathLab/sandbox/pathlab-sandbox-candidate.sif" \
  server/backend/autoresearch/runtime/containers/skills-runtime.def
```

Run `apptainer test` and the verification script under `sandbox_command`'s production
mount/isolation flags before replacing the live SIF. An older migration bundle
still contains its original image; apply this recipe after restoring it or export
a fresh bundle containing the verified SIF.
