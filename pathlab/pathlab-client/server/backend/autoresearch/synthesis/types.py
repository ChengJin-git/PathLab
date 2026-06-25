"""Synthesis data model — reports, claims, and sections."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClaimRecord:
    """One claim in a research report, linked to evidence and citations."""
    claim_id: str
    section: str                     # "abstract" | "results" | "limitations" | "discussion"
    claim_type: str                  # "result" | "comparison" | "limitation" | "method" | "reproducibility"
    statement: str
    evidence_run_ids: list[str] = field(default_factory=list)
    citation_paper_ids: list[str] = field(default_factory=list)
    confidence: str = "high"         # "high" | "medium" | "low"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "section": self.section,
            "claim_type": self.claim_type,
            "statement": self.statement,
            "evidence_run_ids": self.evidence_run_ids,
            "citation_paper_ids": self.citation_paper_ids,
            "confidence": self.confidence,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimRecord:
        return cls(**data)


@dataclass
class ReportSection:
    """One section of a research report."""
    name: str
    title: str
    content: str
    claim_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "content": self.content,
            "claim_ids": self.claim_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportSection:
        return cls(**data)


@dataclass
class ResearchReport:
    """Structured research report assembled from evidence and citations."""
    session_id: str
    conversation_id: str
    objective: str
    success_metric: str
    best_run_id: str
    best_metric_value: float
    claims: list[ClaimRecord] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    comparison_table: list[dict] = field(default_factory=list)
    failure_table: list[dict] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    reproducibility: dict = field(default_factory=dict)
    report_markdown_path: str = ""
    paper_draft_path: str = ""
    # Serialized IntegrityGuard issues, shape mirroring IntegrityIssue dicts
    # ({"code", "severity", "message", "context"}). Kept on the report so
    # the paper writer and any downstream JSON consumers see the fatal/warning
    # rows alongside claims and references.
    integrity_issues: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "objective": self.objective,
            "success_metric": self.success_metric,
            "best_run_id": self.best_run_id,
            "best_metric_value": self.best_metric_value,
            "claims": [c.to_dict() for c in self.claims],
            "sections": [s.to_dict() for s in self.sections],
            "comparison_table": self.comparison_table,
            "failure_table": self.failure_table,
            "references": self.references,
            "reproducibility": self.reproducibility,
            "report_markdown_path": self.report_markdown_path,
            "paper_draft_path": self.paper_draft_path,
            "integrity_issues": self.integrity_issues,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchReport:
        return cls(
            session_id=data["session_id"],
            conversation_id=data["conversation_id"],
            objective=data["objective"],
            success_metric=data["success_metric"],
            best_run_id=data["best_run_id"],
            best_metric_value=data["best_metric_value"],
            claims=[ClaimRecord.from_dict(c) for c in data.get("claims", [])],
            sections=[ReportSection.from_dict(s) for s in data.get("sections", [])],
            comparison_table=data.get("comparison_table", []),
            failure_table=data.get("failure_table", []),
            references=data.get("references", []),
            reproducibility=data.get("reproducibility", {}),
            report_markdown_path=data.get("report_markdown_path", ""),
            paper_draft_path=data.get("paper_draft_path", ""),
            integrity_issues=data.get("integrity_issues", []) or [],
        )


# --- Grounded paper writing contracts ---


@dataclass
class GroundedSectionInput:
    """Scoped input for writing one section of a grounded paper draft."""
    section_name: str
    section_title: str
    section_goal: str
    source_report_section: str
    allowed_claim_ids: list[str] = field(default_factory=list)
    allowed_run_ids: list[str] = field(default_factory=list)
    allowed_paper_ids: list[str] = field(default_factory=list)
    allowed_metric_facts: list[dict] = field(default_factory=list)
    required_caution_flags: list[str] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_name": self.section_name,
            "section_title": self.section_title,
            "section_goal": self.section_goal,
            "source_report_section": self.source_report_section,
            "allowed_claim_ids": self.allowed_claim_ids,
            "allowed_run_ids": self.allowed_run_ids,
            "allowed_paper_ids": self.allowed_paper_ids,
            "allowed_metric_facts": self.allowed_metric_facts,
            "required_caution_flags": self.required_caution_flags,
            "claims": [c.to_dict() for c in self.claims],
            "references": self.references,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroundedSectionInput:
        return cls(
            section_name=data["section_name"],
            section_title=data["section_title"],
            section_goal=data["section_goal"],
            source_report_section=data["source_report_section"],
            allowed_claim_ids=data.get("allowed_claim_ids", []),
            allowed_run_ids=data.get("allowed_run_ids", []),
            allowed_paper_ids=data.get("allowed_paper_ids", []),
            allowed_metric_facts=data.get("allowed_metric_facts", []),
            required_caution_flags=data.get("required_caution_flags", []),
            claims=[ClaimRecord.from_dict(c) for c in data.get("claims", [])],
            references=data.get("references", []),
        )


@dataclass
class DraftVerificationIssue:
    """One issue found during paper draft verification."""
    section_name: str
    issue_type: str       # "unsupported_run_id" | "unsupported_paper_id" | "unsupported_metric"
    severity: str         # "error" | "warning"
    sentence: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_name": self.section_name,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "sentence": self.sentence,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DraftVerificationIssue:
        return cls(**data)


@dataclass
class PaperDraftVerificationResult:
    """Result of verifying a paper draft against report evidence."""
    passed: bool
    issue_count: int = 0
    issues: list[DraftVerificationIssue] = field(default_factory=list)
    unsupported_run_ids: list[str] = field(default_factory=list)
    unsupported_paper_ids: list[str] = field(default_factory=list)
    unsupported_metric_mentions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issue_count": self.issue_count,
            "issues": [i.to_dict() for i in self.issues],
            "unsupported_run_ids": self.unsupported_run_ids,
            "unsupported_paper_ids": self.unsupported_paper_ids,
            "unsupported_metric_mentions": self.unsupported_metric_mentions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperDraftVerificationResult:
        return cls(
            passed=data["passed"],
            issue_count=data.get("issue_count", 0),
            issues=[DraftVerificationIssue.from_dict(i) for i in data.get("issues", [])],
            unsupported_run_ids=data.get("unsupported_run_ids", []),
            unsupported_paper_ids=data.get("unsupported_paper_ids", []),
            unsupported_metric_mentions=data.get("unsupported_metric_mentions", []),
        )


@dataclass
class ScientificCritiqueIssue:
    """One issue found during scientific critique."""
    section_name: str
    category: str          # "overclaim" | "missing_limitations" | "causal_language" | "consistency"
    severity: str          # "error" | "warning" | "info"
    finding: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_name": self.section_name,
            "category": self.category,
            "severity": self.severity,
            "finding": self.finding,
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScientificCritiqueIssue:
        return cls(**data)


@dataclass
class PaperScientificCritiqueResult:
    """Result of scientific critique of a paper draft."""
    passed: bool
    requires_revision: bool = False
    issue_count: int = 0
    issues: list[ScientificCritiqueIssue] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "requires_revision": self.requires_revision,
            "issue_count": self.issue_count,
            "issues": [i.to_dict() for i in self.issues],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperScientificCritiqueResult:
        return cls(
            passed=data["passed"],
            requires_revision=data.get("requires_revision", False),
            issue_count=data.get("issue_count", 0),
            issues=[ScientificCritiqueIssue.from_dict(i) for i in data.get("issues", [])],
            summary=data.get("summary", ""),
        )
