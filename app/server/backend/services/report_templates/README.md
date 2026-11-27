# Report templates

> PathLab v1.0.8 integration · Updated 2026-11-01

MICCAI assets retrieved 2026-10-29 from the official author guidelines:
https://conferences.miccai.org/2026/en/PAPER-SUBMISSION-GUIDELINES.html

- `llncs.cls`, `splncs04.bst`, `readme.txt`, `history.txt`: unmodified files from
  `MICCAI2026-Latex-Template.zip`. Upstream copyright notices are retained.
- `miccai.docx`: official `splnproc2311.docm` from `MICCAI2026-Word-Template.zip`,
  converted to macro-free DOCX by removing VBA/customUI parts and relationships.
  Original styles, page geometry and anonymized author block are retained on export.

Nature Article uses the manuscript submission format described at
https://www.nature.com/nature/for-authors/formatting-guide : 12-point Times New
Roman, double spacing, line numbering, and Article section ordering. This is an
editable submission manuscript, not Nature's typeset print layout. Nature does
not require the Springer Nature `sn-jnl` class for its Article submissions.

Automatic selection is a PathLab product heuristic: at least six completed runs
across at least two recorded datasets selects `journal`; otherwise `conference`. These
are the API/UI template IDs; the upstream asset names retain provenance. Selection is
independent of requested effort and is not a judgement of publication readiness.

`fonts/` bundles unmodified Liberation Sans Regular/Bold under SIL OFL 1.1
(see fonts/LICENSE.txt). These Arial metric-compatible fonts are used for
Nature-style research figures; PDF embeds TrueType and SVG preserves editable text.
