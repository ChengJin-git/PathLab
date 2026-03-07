from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any


class _ToolEventRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._started: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def clear_thread(self, thread_id: str) -> None:
        if not thread_id:
            return
        with self._lock:
            self._pending.pop(thread_id, None)
            self._started.pop(thread_id, None)

    def register_tool_calls(
        self,
        thread_id: str,
        message_id: str,
        agent: str,
        tool_calls: list[dict[str, Any]],
    ) -> None:
        if not thread_id or not message_id or not tool_calls:
            return
        with self._lock:
            queue = self._pending[thread_id]
            for tool_call in tool_calls:
                tool_call_id = tool_call.get("id")
                tool_name = tool_call.get("name")
                if not tool_call_id or not tool_name:
                    continue
                queue.append(
                    {
                        "thread_id": thread_id,
                        "id": message_id,
                        "agent": agent,
                        "role": "assistant",
                        "tool_call_id": str(tool_call_id),
                        "tool_name": str(tool_name),
                    }
                )

    def mark_tool_started(self, thread_id: str, tool_name: str) -> None:
        if not thread_id or not tool_name:
            return
        with self._lock:
            queue = self._pending.get(thread_id)
            if not queue:
                return
            for index, entry in enumerate(queue):
                if entry.get("tool_name") == tool_name:
                    self._started[thread_id].append(dict(entry))
                    del queue[index]
                    if not queue:
                        self._pending.pop(thread_id, None)
                    return

    def mark_tool_finished(self, thread_id: str, tool_call_id: str) -> None:
        if not thread_id or not tool_call_id:
            return
        with self._lock:
            queue = self._pending.get(thread_id)
            if not queue:
                return
            filtered = [entry for entry in queue if entry.get("tool_call_id") != tool_call_id]
            if filtered:
                self._pending[thread_id] = filtered
            else:
                self._pending.pop(thread_id, None)

    def drain_started_events(self, thread_id: str) -> list[dict[str, Any]]:
        if not thread_id:
            return []
        with self._lock:
            return self._started.pop(thread_id, [])


_REGISTRY = _ToolEventRegistry()


def clear_thread_tool_events(thread_id: str) -> None:
    _REGISTRY.clear_thread(thread_id)


def register_pending_tool_calls(
    thread_id: str,
    message_id: str,
    agent: str,
    tool_calls: list[dict[str, Any]],
) -> None:
    _REGISTRY.register_tool_calls(thread_id, message_id, agent, tool_calls)


def notify_tool_started(thread_id: str, tool_name: str) -> None:
    _REGISTRY.mark_tool_started(thread_id, tool_name)


def mark_tool_finished(thread_id: str, tool_call_id: str) -> None:
    _REGISTRY.mark_tool_finished(thread_id, tool_call_id)


def drain_started_tool_events(thread_id: str) -> list[dict[str, Any]]:
    return _REGISTRY.drain_started_events(thread_id)