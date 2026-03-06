# src/utils/token_tracker.py
"""Token usage tracker for recording actual LLM API token consumption.

Captures token usage from AIMessageChunk objects during LangGraph streaming.
Usage data is extracted from usage_metadata or response_metadata on message chunks.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LLMCallRecord:
    """Record of a single LLM API call's token usage."""

    agent: str  # Which agent produced this call (coordinator, planner, researcher...)
    node: str  # LangGraph node name
    prompt_tokens: int = 0  # Input tokens
    completion_tokens: int = 0  # Output tokens
    total_tokens: int = 0
    model: str = ""
    timestamp: float = field(default_factory=time.time)


class TokenUsageTracker:
    """Track all LLM token usage for a single conversation thread.

    Usage data is captured from AIMessageChunk objects in the streaming pipeline.
    Supports deduplication to avoid counting the same LLM call multiple times.

    Usage:
        tracker = TokenUsageTracker(thread_id="abc123")

        # Record from streaming chunks
        tracker.record("coordinator", "coordinator_node", 800, 200)

        # Check for duplicates
        if not tracker.has_usage_for_chunk("chunk-id"):
            tracker.record(...)

        # Get summary for SSE event
        summary = tracker.get_summary()
    """

    def __init__(self, thread_id: str = ""):
        self.thread_id = thread_id
        self.calls: list[LLMCallRecord] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self._by_agent: dict[str, dict] = {}
        self._recorded_chunk_ids: set[str] = set()  # For deduplication

    def record(
        self,
        agent: str,
        node: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int = 0,
        model: str = "",
        chunk_id: str = "",
    ):
        """Record a single LLM call's token usage.

        Args:
            agent: Agent name (e.g., "coordinator", "researcher")
            node: LangGraph node name (e.g., "coordinator_node")
            prompt_tokens: Number of input/prompt tokens
            completion_tokens: Number of output/completion tokens
            total_tokens: Total tokens (auto-calculated if 0)
            model: Model name (optional)
            chunk_id: Message chunk ID for deduplication (optional)
        """
        if prompt_tokens == 0 and completion_tokens == 0:
            return  # Skip empty records

        # Deduplication: skip if we've already recorded this chunk
        if chunk_id and chunk_id in self._recorded_chunk_ids:
            return
        if chunk_id:
            self._recorded_chunk_ids.add(chunk_id)

        calculated_total = total_tokens or (prompt_tokens + completion_tokens)

        record = LLMCallRecord(
            agent=agent,
            node=node,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=calculated_total,
            model=model,
        )
        self.calls.append(record)

        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens

        # Accumulate per-agent stats
        if agent not in self._by_agent:
            self._by_agent[agent] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
            }
        self._by_agent[agent]["prompt_tokens"] += prompt_tokens
        self._by_agent[agent]["completion_tokens"] += completion_tokens
        self._by_agent[agent]["total_tokens"] += calculated_total
        self._by_agent[agent]["calls"] += 1

        tid = self.thread_id[:8] if self.thread_id else "?"
        logger.info(
            f"[TokenTracker][{tid}] {agent}/{node}: "
            f"prompt={prompt_tokens}, completion={completion_tokens}, "
            f"total={calculated_total}"
            f"{f', model={model}' if model else ''} | "
            f"Cumulative: {self.total_prompt_tokens}+{self.total_completion_tokens}"
            f"={self.total_prompt_tokens + self.total_completion_tokens}"
        )

    def get_summary(self) -> dict:
        """Get usage summary suitable for sending to the frontend as an SSE event.

        Returns:
            Dictionary with total counts, per-agent breakdown, and call details.
        """
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "total_calls": len(self.calls),
            "by_agent": {
                agent: {**stats} for agent, stats in self._by_agent.items()
            },
            "details": [
                {
                    "agent": c.agent,
                    "node": c.node,
                    "prompt_tokens": c.prompt_tokens,
                    "completion_tokens": c.completion_tokens,
                    "total_tokens": c.total_tokens,
                    "model": c.model,
                }
                for c in self.calls
            ],
        }

    def has_data(self) -> bool:
        """Check if any token usage has been recorded."""
        return len(self.calls) > 0
