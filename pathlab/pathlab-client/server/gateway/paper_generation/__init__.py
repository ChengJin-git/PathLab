"""
PathLab Paper Generation Agent
================================

PaperOrchestra-aligned multi-agent pipeline that turns a completed PathLab
experiment into submission-ready LaTeX manuscripts (MICCAI + Nature Scientific
Reports).

See `docs/plan/paper_generation_agent_design.md` for the full design.

Phase 1 (M1) deliverables in this package:
- `routes`: API endpoints (POST /papers, GET /papers, file allowlist)
- `schemas`: Pydantic request/response models
- `storage`: filesystem layout and path helpers for `uploads/paper_generation/`
- `pipeline`: orchestration entrypoint (stub in M1, fleshed out M2+)
- `llm.client`: LLM provider abstraction (multimodal-capable)

Subsequent milestones add:
- `collector/` (M2)
- `evidence/`, `phi_scrub.py` (M3)
- `agents/` (M6b/M7/M8b/M9/M11)
- `plotting/` (M6a/M6c)
- `citations/` (M8a)
- `validators/` (M10a/M10b)
- `renderers/` (M5/M9/M12)
"""

__all__ = []
