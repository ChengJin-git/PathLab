"""The persisted visible branch, independent of insertion order or process state."""


def visible_messages(messages):
    ordered = sorted(messages, key=lambda message: message.id)
    groups = {}
    for message in ordered:
        if (getattr(message, "extra_metadata", None) or {}).get(
            "superseded_by_regeneration"
        ):
            continue
        if message.variant_group_id:
            groups.setdefault(message.variant_group_id, []).append(message)
    emitted, result = set(), []
    for message in ordered:
        if (getattr(message, "extra_metadata", None) or {}).get(
            "superseded_by_regeneration"
        ):
            continue
        group = message.variant_group_id
        if not group:
            result.append(message)
        elif group not in emitted:
            emitted.add(group)
            # A regenerated row is appended to storage, but belongs at the
            # original answer's position. Legacy duplicate-active groups show
            # only their latest selection, never multiple answer bubbles.
            active = [item for item in groups[group] if item.is_active_variant]
            if active:
                result.append(active[-1])
    return result
