# Bundled research skills

> PathLab v1.0.8 integration · Updated 2026-11-24

Pinned, complete skill packages used by the PathLab research sandbox and text writer.
`sources.lock.json` records upstream commits, archive hashes and every file hash.
`deploy/sync-research-skills.py` reproduces this snapshot without executing upstream
installers, hooks or auto-update code. Upstream source and license files are retained.
Nested Markdown files are versioned upstream resources, not PathLab release documents.
Their original dates, examples, license notices and evaluation fixtures form the pinned
snapshot; update the collection through the sync tool and its hashes when changing sources.

- `nature-skills/skills`: 23 functional skills plus `nature-shared`, including full
  static fragments, references, scripts, templates, assets and third-party notices.
  Source: https://github.com/Yuan1z0825/nature-skills (Apache-2.0; nested assets retain
  their own notices). This is a community project, not a publisher-issued product.
- `editing/humanizer`: https://github.com/blader/humanizer (MIT).
- `editing/humanizer-zh`: https://github.com/op7418/Humanizer-zh (MIT).
- `pathtrove`: https://github.com/DearCaat/PathTrove `plugin/` (documentation licence plus
  research-use terms in `TERMS_OF_USE.md`). A stdlib-only MCP server and three skills
  (`pathtrove`, `pathtrove-data`, `pathtrove-best-data`) over a curated catalogue of 350+ public
  computational-pathology datasets, challenges and benchmarks. Its `data-manifest.json` pins the
  data archive (version, size, SHA-256) on Hugging Face; `engine/pathtrove.py` installs exactly that
  archive under `<autoresearch dir>/pathtrove` (`deploy/install-pathtrove-data.py`, run by
  `deploy/start.sh`), mounted read-only at `/opt/pathlab/pathtrove`. OpenCode runs the server as
  MCP `pathtrove`; tools use the `pathtrove_` prefix. Upgrading = change the commit in
  `deploy/sync-research-skills.py`, sync, then rerun the installer for the new data version.

The sandbox mounts this directory read-only at `/opt/pathlab/skill-library` and
OpenCode discovers skills from explicit source directories. Assets are not copied
into every session/run snapshot. Optional services (publisher APIs, browser login,
image generation, R, Zotero, external MCP servers) need their documented dependencies;
installing the skill does not configure those accounts. Use PathLab's existing
authorized data acquisition and verified citation tools first.
The installed sandbox tools and optional credential paths are documented in
[`../runtime/containers/SKILLS-RUNTIME.md`](../runtime/containers/SKILLS-RUNTIME.md).

The six pathology task guides are exposed separately as `pathlab-*` native skills.
The core `pathlab-research` instruction routes planning, data, literature, statistics,
writing, review, figures and language editing to the relevant packages.

Text-only article generation resolves the actual `nature-writing` manifest fragments
per section. Final review and interactive polishing use `nature-polishing` plus the
full English Humanizer or Chinese Humanizer-zh. Selected paths and SHA-256 are recorded
in generation progress. Scientific facts, citation identifiers, uncertainty, selected
language and conference/journal template naming override style-only preferences.

No upstream package is run simply because it is installed. Skills load progressively
for applicable tasks. External-review workflows must not claim independent reviewers
unless separate contexts were actually used. Scholarly retrieval is not restricted to
a publisher family unless the user's literature task explicitly requests that scope.
