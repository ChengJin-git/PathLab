"""Helpers for locking experiment data protocol across ratchet runs."""
from __future__ import annotations


DATA_PROTOCOL_KEYS = (
    "n_train",
    "n_val",
    "n_test",
    "n_classes",
    "dataset_path",
    "data_dir",
    "split_source",
    "split_hash",
    "data_protocol_hash",
)
REQUIRED_DATA_PROTOCOL_KEYS = ("n_train", "n_val", "n_test")


def normalize_data_protocol_value(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def extract_data_protocol(metrics: dict | None) -> dict:
    """Return the benchmark data protocol encoded in a metrics dict.

    Quick-check metrics are ignored because they use intentionally tiny caps
    and must not lock the scientific comparison protocol.
    """
    if not isinstance(metrics, dict) or metrics.get("quick_check") is True:
        return {}
    out = {}
    for key in DATA_PROTOCOL_KEYS:
        value = metrics.get(key)
        if value is None or value == "":
            continue
        out[key] = normalize_data_protocol_value(value)
    if not all(key in out for key in REQUIRED_DATA_PROTOCOL_KEYS):
        return {}
    return out


def locked_data_protocol_from_tracker(tracker) -> tuple[dict, str, int | None]:
    """Find the first committed full-run protocol in tracker history."""
    if tracker is None:
        return {}, "", None
    history = getattr(tracker, "history", []) or []
    for row in history:
        if not isinstance(row, dict) or not row.get("committed"):
            continue
        protocol = extract_data_protocol(row.get("metrics"))
        if protocol:
            return protocol, str(row.get("run_id", "")), row.get("iteration")
    return {}, "", None


def format_data_protocol(protocol: dict) -> str:
    return ", ".join(f"{key}={protocol.get(key)!r}" for key in protocol)


def data_protocol_change_message(
    *,
    locked: dict,
    current: dict,
    run_id: str,
    iteration,
    tool_name: str = "ratchet_commit",
) -> str:
    changes = []
    for key, locked_value in locked.items():
        if key not in current:
            changes.append(f"{key}: locked={locked_value!r}, current=<missing>")
        elif current[key] != locked_value:
            changes.append(
                f"{key}: locked={locked_value!r}, current={current[key]!r}"
            )
    changed_text = "; ".join(changes) if changes else "<unknown>"
    source = f"run_id={run_id or '<unknown>'}"
    if iteration is not None:
        source += f", iteration={iteration}"
    return (
        f"\u274c {tool_name} refused: data protocol changed after the first "
        "committed full run.\n"
        f"  Locked protocol ({source}): {format_data_protocol(locked)}\n"
        f"  Current protocol: {format_data_protocol(current) or '<missing>'}\n"
        f"  Differences: {changed_text}\n"
        "  Keep n_train/n_val/n_test, split source/hash, and dataset identity "
        "fixed when comparing runs in the same ratchet ladder. Re-run with "
        "the locked protocol or call ratchet_revert. Treat data-size/split "
        "changes as a separate ablation, not as an improvement commit."
    )
