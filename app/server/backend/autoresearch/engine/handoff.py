"""Bounded, authorized chat context for research; no extra model request."""

import re
from backend.common.chat_timeline import visible_messages


def conversation_context(messages) -> dict:
    visible = [
        m
        for m in visible_messages(messages)
        if m.role in {"user", "assistant"}
    ]
    selected = visible[-24:]
    first = next((m for m in visible if m.role == "user"), None)
    if first and first not in selected:
        selected = [first, *selected]
    entries = []
    for message in selected:
        content = str(message.content)
        # Handoff cards repeat the summary; raw binary attachments add no intent.
        content = re.sub(r"\[NAVIGATE\][\s\S]*?\[/NAVIGATE\]", "", content, flags=re.I)
        content = re.sub(
            r"data:[^\s;]+;base64,[A-Za-z0-9+/=]+", "[attachment in Chat]", content
        )
        content = content.strip()
        if content:
            entries.append(f"{message.role}: {content[:3000]}")
    context = "\n\n".join(entries)
    if len(context) > 24000:
        context = (
            context[:3000]
            + "\n\n[Earlier context trimmed; recent corrections follow]\n\n"
            + context[-20000:]
        )
    return {
        "context": context,
        "message_count": len(visible),
        "included_messages": len(entries),
    }
