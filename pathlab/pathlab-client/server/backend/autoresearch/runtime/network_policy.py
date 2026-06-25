"""Unified network policy for literature acquisition paths.

Plan-2026-04-29 literature-acquisition Phase 1: each online leg (paper
search / SOTA lookup / RAG dense) consults this policy instead of its
own binary toggle. Stage semantics:

- ``local``  — no network at all. Local stores and existing caches still
                allowed. Tests + reproducibility runs.
- ``cached`` — cache/local lookup allowed, but new network calls refused.
                Once Phase 2 lands paper/RAG caches, this serves them
                without touching OpenAlex/PwC/embedding endpoint.
- ``auto``   — try network, gracefully fall back to local on failure.
                Historical default behavior.
- ``full``   — try network, fail hard (raise ``NetworkUnavailableError``)
                if any allowed leg cannot reach. Live smoke / debugging.

Per-component overrides (``allow_papers`` / ``allow_sota`` /
``allow_rag_dense``) are AND-ed with the stage. Setting any to False
forces that leg off regardless of stage.

``refresh`` is a set of leg names (``"sota"`` / ``"papers"`` /
``"rag_dense"``) plus the special ``"all"``; legs listed there bypass
their cache and re-query the source (subject to stage gating).

``fail_hard_override`` lets a caller opt into raise-on-failure without
committing to ``stage="full"`` (e.g. an ``auto`` run that wants to abort
on a specific leg's failure).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Stage = Literal["local", "cached", "auto", "full"]
LegName = Literal["papers", "sota", "rag_dense", "dataset_discovery"]
LegState = Literal[
    "ok",
    "error",
    "disabled",
    "cached",
    "refused",
    "not_invoked",
]


class NetworkUnavailableError(RuntimeError):
    """Raised when fail-hard policy requires aborting on network failure.

    Reproducibility / live-smoke runs catch this at the orchestrator
    boundary so a degraded result never silently passes for a successful
    one.
    """


@dataclass
class NetworkPolicy:
    """Control whether each literature online leg may call network.

    See module docstring for stage semantics.
    """

    stage: Stage = "local"
    allow_papers: bool = True
    allow_sota: bool = True
    allow_rag_dense: bool = True
    refresh: set[str] = field(default_factory=set)
    fail_hard_override: bool = False
    # Plan-2026-04-29 literature-acquisition Phase 5 / Task 3:
    # gate auto-ingestion (write online paper hits into PaperRegistry +
    # PassageIndex). Default False because storage growth + freshness
    # are sensitive — opt-in.
    allow_auto_ingest: bool = False
    # Plan-2026-04-30 dataset-discovery T11: gate the literature-grounded
    # dataset discovery leg. Default True — heuristic extraction reads
    # only persisted grounding outputs and is offline-safe; the leg is
    # reserved for the optional LLM extractor / Phase 5b PDF probe paths.
    allow_dataset_discovery: bool = True

    def is_leg_enabled(self, leg: LegName) -> bool:
        """Whether the leg is logically enabled (cache OR network may serve)."""
        if self.stage == "local":
            return False
        return bool(getattr(self, f"allow_{leg}"))

    def allows_network(self, leg: LegName) -> bool:
        """Whether a fresh network call for this leg is permitted.

        ``cached`` stage returns False — only cache/local hits OK.
        """
        return self.stage in {"auto", "full"} and self.is_leg_enabled(leg)

    def is_cache_only(self) -> bool:
        return self.stage == "cached"

    def should_fail_hard(self) -> bool:
        return self.stage == "full" or self.fail_hard_override

    def should_refresh(self, leg: LegName) -> bool:
        return leg in self.refresh or "all" in self.refresh

    def auto_ingest_enabled(self) -> bool:
        """Phase 5: whether ``LiteratureService.ingest`` may write to the
        registry / passage index. Stage ``"local"`` always disables (no
        sense ingesting from offline runs); other stages honor the
        explicit ``allow_auto_ingest`` flag."""
        if self.stage == "local":
            return False
        return self.allow_auto_ingest


@dataclass
class NetworkLegStatus:
    """Per-leg telemetry. Recorded by each retriever after its call."""

    leg: str
    state: LegState
    provider: str = ""
    count: int = 0
    error: str = ""
    cache_age_sec: float = -1.0

    def to_dict(self) -> dict:
        return {
            "leg": self.leg,
            "state": self.state,
            "provider": self.provider,
            "count": self.count,
            "error": self.error,
            "cache_age_sec": self.cache_age_sec,
        }


@dataclass
class NetworkStatus:
    """Aggregated network status for one grounding pass.

    Emitted on the grounding dict as ``network_status`` so a single
    structured object captures all three legs' behavior.
    """

    policy: NetworkPolicy
    legs: dict[str, NetworkLegStatus] = field(default_factory=dict)

    def record(self, leg: str, status: NetworkLegStatus) -> None:
        self.legs[leg] = status

    def to_dict(self) -> dict:
        return {
            "policy": {
                "stage": self.policy.stage,
                "allow_papers": self.policy.allow_papers,
                "allow_sota": self.policy.allow_sota,
                "allow_rag_dense": self.policy.allow_rag_dense,
                "refresh": sorted(self.policy.refresh),
                "fail_hard": self.policy.should_fail_hard(),
            },
            "legs": {
                name: status.to_dict() for name, status in self.legs.items()
            },
        }


def _env_truthy(name: str) -> bool:
    import os

    return os.environ.get(name, "").lower() in {"1", "true", "yes"}


def network_policy_from_config(config) -> NetworkPolicy:
    """Build NetworkPolicy from legacy AutoResearchConfig flags.

    Plan-2026-04-29 literature-acquisition Phase 1 / Task 2: this shim
    intentionally lives outside ``config.py`` because CLI/config files are
    user WIP. Phase 1.5 (CLI integration) will replace it with first-class
    config fields + ``--network=...`` flag.

    Behavior preserved from current runner:
    - ``stage="auto"`` so failures gracefully fall back to local.
    - ``allow_papers`` mirrors ``literature_online_enabled`` (default False).
    - ``allow_sota`` mirrors ``not no_online_sota`` (default True). The
      ``no_online_sota`` attribute may be set dynamically on the config
      instance, OR via env var ``AUTORESEARCH_NO_ONLINE_SOTA``.
    - ``allow_rag_dense`` mirrors ``literature_rag_enabled`` (default False).
    - ``refresh={"sota"}`` when ``refresh_sota=True``; future flags will
      add ``"papers"`` / ``"rag_dense"`` / ``"all"``.

    ``config=None`` returns a fully-local policy (test default).
    """
    if config is None:
        return NetworkPolicy()

    no_online_sota = bool(getattr(config, "no_online_sota", False)) or _env_truthy(
        "AUTORESEARCH_NO_ONLINE_SOTA"
    )
    refresh: set[str] = set()
    if bool(getattr(config, "refresh_sota", False)):
        refresh.add("sota")

    # Plan-2026-04-30 dataset-discovery T11: forward-compat env + attr.
    # CLI flags (--dataset-discovery / --no-dataset-discovery) defer to
    # Phase 1.5; here we honor an explicit attribute on the config and
    # the ``AUTORESEARCH_DATASET_DISCOVERY=0`` env disable.
    import os as _os
    raw_dd_env = _os.environ.get("AUTORESEARCH_DATASET_DISCOVERY", "")
    if raw_dd_env.lower() in {"0", "false", "no"}:
        dataset_discovery_enabled = False
    else:
        dataset_discovery_enabled = bool(
            getattr(config, "dataset_discovery_enabled", True)
        )

    return NetworkPolicy(
        stage="auto",
        allow_papers=bool(getattr(config, "literature_online_enabled", False)),
        allow_sota=not no_online_sota,
        allow_rag_dense=bool(getattr(config, "literature_rag_enabled", False)),
        allow_dataset_discovery=dataset_discovery_enabled,
        refresh=refresh,
    )
