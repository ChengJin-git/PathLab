# Editable research reports

> PathLab v1.0.8 · Updated 2026-11-06

## One workflow

The `/reports` page starts from one authorized completed training experiment or
an AutoResearch session with completed model experiments. It snapshots recorded
configuration, metrics and task-bound analysis summaries into `manuscripts`.
Creating a report queues an LLM writing task using the selected document structure.
The home page lists recent articles across sources, with server-side owner filtering
(admin: all, pathologist: own, guest: denied), search and pagination.
Downloading data, preparing inputs and computing metrics without experiments do
not create manuscripts or require them for completion.

`manuscripts.py` owns evidence, template selection, drafts and versioned saves.
`report_export.py` owns native editable Word and escaped LaTeX source rendering.
`text_editor.py` is the shared bounded editor for research briefs and manuscripts.
`manuscript_writer.py` runs durable jobs through the existing ResearchWorker:
evidence analysis → scholarly retrieval → section writing → full-article review.
It uses the configured research model. Each completed section is checkpointed in
`manuscript_generations`; incomplete provider responses are never published. Manual
writing can resume via the report page; autonomous writing resumes via the research
recovery panel. The writing queue has two independent API/CPU slots and needs no GPU.

Scientific writing guidance comes from the pinned full skill library under
`backend/autoresearch/skill_library/`. The writer selects complete `nature-writing`
manifest fragments for planning and each section. Its final pass combines
`nature-polishing` with English Humanizer or Humanizer-zh. Interactive editing uses
the same references, chooses language from the passage/translation request, and
checks numeric values, citations and protected syntax before returning a suggestion.
The selected paths/hashes appear in `ManuscriptGeneration.progress.skill_contexts`.
The service validates evidence and references independently of writing guidance.

## APIs

Gateway exposes these paths directly and under `/api`:

- `GET /reports/sources?query=`: owner-scoped completed results (admin sees all).
- `GET /reports/templates`: conference/journal template names and structure.
- `GET /reports/documents?query=&cursor=`: 20 recent article summaries, owner names
  and lightweight writing status. Returns `next_cursor` and `page_size`; optional
  source_type/source_id filters narrow the list. Pages use immutable creation time
  plus report ID, so editing/writing does not reorder articles between requests.
  SQL selects page IDs first, then a 240-character excerpt and scalar state fields;
  complete content/evidence/generation JSON and word counting are excluded. Indexes
  cover global and owner-specific creation order in the current schema.
  The frontend keeps previous-page cursors, debounces search by 300 ms, cancels stale
  requests, and refreshes only visible pages with active writing tasks.
- `GET /reports/source?source_type=…&source_id=…`: authorized result and template recommendation.
- `POST /reports/documents`: enqueue LLM writing with source, template, language and instruction.
- `POST /reports/documents/{id}/resume`: resume a failed/interrupted manual writing job.
- `GET|PUT /reports/documents/{id}`: content, template, status and optimistic revision.
- `DELETE /reports/documents/{id}`: delete a completed report or settled draft and
  its report-only assets. Admin can delete all, pathologist only their own; guest is
  denied. Queued/running jobs return 409. The generation lock serializes deletion
  with resume; research report links/artifact registrations are cleared, while source
  experiments and their results are retained.
- `POST /reports/documents/{id}/polish`: selected passage or full-manuscript suggestion.
  Uses saved text/evidence; UTF-16 browser selections are decoded explicitly.
  Returns a suggestion only. The user applies/discards/undoes it in the editor.
- `GET /reports/documents/{id}/download/docx|latex`: authenticated export.
- `GET /reports/documents/{id}/figures/{filename}`: authenticated, snapshotted figure.

All operations recheck role, ownership and source/workspace access. Draft exports
are visibly marked incomplete. Changing templates reorders known sections and
retains custom content. Evidence snapshots are immutable when editing prose.
Template IDs are `conference` and `journal` throughout API, MCP, database and download
names. The original template asset/license provenance remains in the repository.

Writing requests have bounded wall-clock time: 120 seconds per section, 480 seconds
for the full-article review. A transient timeout/rate limit/5xx is retried once after
rechecking access and remaining research budget. Authentication errors are not retried.
Unknown citations trigger one editorial repair against the same retrieved references;
continued failure remains a recoverable draft. Numeric confusion matrices are not
interpreted as bibliography markers. Completed sections survive all of these retries.

## Autonomous publication and interruption

Agents call `generate_article` to enqueue/resume the same scientific writer used by
the manual page, then end their turn. The supervisor waits for writing and notifies
the agent after completion. Publication creates Word, Markdown and LaTeX ZIP artifacts
and a `ready` manuscript. Missing core sections, missing/unknown citations or a budget
expiry during conversion leave a saved draft. `save_report_draft` remains a checkpoint
for agent-authored notes, not a replacement for LLM article generation.
`finish_research` requires current exports when the effective report policy calls for a manuscript. Summary-only experiments and download/computation/document work can finish with their requested deliverables.

Scientific studies require a current `write` review tied to protocol steps, matching runs and recorded decisions. The writer snapshots only the reviewed evidence and figures. Goal, protocol, run or source changes invalidate stale reviews; draft saving and historical report reading remain available independently.

`engine/budget.py` implements cooperative budget shutdown:

1. Warn near the time limit and encourage section-level checkpoints.
2. At time expiry, or when an additional required experiment exceeds the attempt
   limit, block new jobs/publication and queue a checkpoint-only instruction.
3. Allow at most 120 seconds to save sections and pending work. Block with reason
   `budget`; if a provider remains active, preserve public partial output to
   `budget-checkpoint.json` before interrupting. Partial output is never a final report.
4. Existing independent TaskWorker jobs retain their own timeout/cancellation state.
5. The existing `/research/sessions/{id}/continue` accepts
   `additional_time_seconds` (new execution window, 60 to 259200 seconds) and
   `additional_experiments`. It preserves native conversation, runs and drafts.
   Queue waiting does not consume this window. Zero time uses the existing window.

Reaching exactly the allowed number of completed experiments does not itself
prevent writing within remaining time. Attempting another experiment triggers
the recoverable budget checkpoint.

## Deployment

Deploy Gateway, ResearchWorker and frontend together with the database version in [database/README.md](../database/README.md). Fresh installations create `manuscripts` and `manuscript_generations`; existing schemas are validated rather than migrated at startup. Keep `report_templates/` in deployments and include `python-docx>=1.2.0`, `markdown-it-py>=3.0.0` and `matplotlib>=3.8.0`. Runtime verification checks these dependencies. Template provenance is recorded in that directory.

Server export does not compile TeX or require LibreOffice. The LaTeX ZIP is
editable in Overleaf; local compilation uses XeLaTeX with fontspec/longtable and
xeCJK/Fandol when Chinese characters occur. MICCAI includes the official LNCS class.
Nature follows the Article submission manuscript, not the final print typesetting.

## Scholarly citations

- Europe PMC/PubMed: `https://www.ebi.ac.uk/europepmc/webservices/rest/search`, core
  records include title, authors, journal, publication year, PMID/DOI and abstract.
- Crossref: `https://api.crossref.org/works`, publisher-deposited metadata. Documentation:
  https://www.crossref.org/documentation/retrieve-metadata/rest-api/ .
- Optional Google Scholar discovery: set `PATHLAB_SERPAPI_KEY`; the SerpApi Scholar
  endpoint is **third-party**, not Google-issued. Candidates must match a Crossref
  title and have registry abstract/metadata before use. No scraping/CAPTCHA bypass.
  Google itself declines bulk access: https://scholar.google.com/intl/en/scholar/help.html .

The shared MCP `search_verified_citations` exposes the registry retrieval function.
No model-authored bibliography or unverified local seed record is accepted as a
citation source. At least two retrieved citations must appear in the completed
article. References are renumbered by first appearance and bibliographies/BibTeX are
rendered from the retrieved records, preserving source URL and timestamp. Registry
retrieval establishes bibliographic provenance; authors still review the argument
and whether each cited abstract supports its use.

## Nature-style figures

Guidance: https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/ .
Generated plots use a 90 mm single-column canvas, 5 to 7 pt sans-serif text, visible axes
and ticks, no background grid, and accessible colours. Liberation Sans (SIL OFL 1.1,
Arial metric-compatible) is bundled with its license. PDF embeds TrueType (type 42);
SVG retains editable text and embeds the font, PNG exports at 450 dpi. LaTeX bundles
PNG/SVG/PDF, underlying figure data JSON, fonts/license, references.json and references.bib.
Word embeds the figures at their intended width with editable captions.

ROC, confusion and loss plots are redrawn from recorded numerical analysis data.
Other figures show exact recorded metric/split values without inferred uncertainty.
Original experiment images retain their pixels; raster scientific charts lacking
underlying data are not relabelled as newly styled Nature plots. No plot is inferred
from a single summary AUC, no missing matrix entries/predictions are fabricated.
