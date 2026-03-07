# src/utils/context_manager.py
import copy
import json
import logging
from typing import List

from langgraph.runtime import Runtime 

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

logger = logging.getLogger(__name__)


def _hoist_system_messages(messages: list) -> list:
    """Move all system messages to the beginning of the list.

    Some LLM providers (e.g. vLLM/Qwen) require system messages to appear
    before any other role.  This helper collects every system message,
    merges them into a single leading SystemMessage, and returns the
    reordered list without mutating the original.
    """
    system_parts: list[str] = []
    non_system: list = []
    for m in messages:
        if isinstance(m, SystemMessage):
            system_parts.append(m.content if isinstance(m.content, str) else str(m.content))
        elif isinstance(m, dict) and m.get("role") == "system":
            system_parts.append(m.get("content", ""))
        else:
            non_system.append(m)
    if not system_parts:
        return messages
    merged_system = SystemMessage(content="\n\n".join(system_parts))
    return [merged_system] + non_system


class ContextManager:
    """Context manager and compression class"""

    def __init__(self, token_limit: int, preserve_prefix_message_count: int = 0):
        """
        Initialize ContextManager

        Args:
            token_limit: Maximum token limit
            preserve_prefix_message_count: Number of messages to preserve at the beginning of the context
        """
        self.token_limit = token_limit
        self.preserve_prefix_message_count = preserve_prefix_message_count

    def count_tokens(self, messages: List[BaseMessage]) -> int:
        """
        Count tokens in message list

        Args:
            messages: List of messages

        Returns:
            Number of tokens
        """
        total_tokens = 0
        for message in messages:
            total_tokens += self._count_message_tokens(message)
        return total_tokens

    def _count_message_tokens(self, message: BaseMessage) -> int:
        """
        Count tokens in a single message

        Args:
            message: Message object

        Returns:
            Number of tokens
        """
        # Estimate token count based on character length (different calculation for English and non-English)
        token_count = 0

        # Count tokens in content field
        if hasattr(message, "content") and message.content:
            # Handle different content types
            if isinstance(message.content, str):
                token_count += self._count_text_tokens(message.content)

        # Count role-related tokens
        if hasattr(message, "type"):
            token_count += self._count_text_tokens(message.type)

        # Special handling for different message types
        if isinstance(message, SystemMessage):
            # System messages are usually short but important, slightly increase estimate
            token_count = int(token_count * 1.1)
        elif isinstance(message, HumanMessage):
            # Human messages use normal estimation
            pass
        elif isinstance(message, AIMessage):
            # AI messages may contain reasoning content, slightly increase estimate
            token_count = int(token_count * 1.2)
        elif isinstance(message, ToolMessage):
            # Tool messages may contain large amounts of structured data, increase estimate
            token_count = int(token_count * 1.3)

        # Process additional information in additional_kwargs
        if hasattr(message, "additional_kwargs") and message.additional_kwargs:
            # Simple estimation of extra field tokens
            extra_str = str(message.additional_kwargs)
            token_count += self._count_text_tokens(extra_str)

            # If there are tool_calls, add estimation
            if "tool_calls" in message.additional_kwargs:
                token_count += 50  # Add estimation for function call information

        # Ensure at least 1 token
        return max(1, token_count)

    def _count_text_tokens(self, text: str) -> int:
        """
        Count tokens in text with different calculations for English and non-English characters.
        English characters: 4 characters ≈ 1 token
        Non-English characters (e.g., Chinese): 1 character ≈ 1 token

        Args:
            text: Text to count tokens for

        Returns:
            Number of tokens
        """
        if not text:
            return 0

        english_chars = 0
        non_english_chars = 0

        for char in text:
            # Check if character is ASCII (English letters, digits, punctuation)
            if ord(char) < 128:
                english_chars += 1
            else:
                non_english_chars += 1

        # Calculate tokens: English at 4 chars/token, others at 1 char/token
        english_tokens = english_chars // 4
        non_english_tokens = non_english_chars

        return english_tokens + non_english_tokens

    def is_over_limit(self, messages: List[BaseMessage]) -> bool:
        """
        Check if messages exceed token limit

        Args:
            messages: List of messages

        Returns:
            Whether limit is exceeded
        """
        return self.count_tokens(messages) > self.token_limit

    def compress_messages(self, state: dict, runtime: Runtime | None = None) -> dict:
        """
        Compress messages to fit within token limit

        Args:
            state: state with original messages
            runtime: Optional runtime parameter (not used but required for middleware compatibility)

        Returns:
            Compressed state with compressed messages, or None when called as
            a pre-model middleware hook and no compression was needed (prevents
            the add_messages reducer from duplicating messages).
        """
        # If not set token_limit, return original state
        if self.token_limit is None:
            logger.info("No token_limit set, the context management doesn't work.")
            # When called as middleware hook, return None to avoid add_messages
            # duplication; when called directly, return the state unchanged.
            return None if runtime is not None else state

        if not isinstance(state, dict) or "messages" not in state:
            logger.warning("No messages found in state")
            return None if runtime is not None else state

        messages = state["messages"]

        if not self.is_over_limit(messages):
            logger.debug(f"Messages within limit ({self.count_tokens(messages)} <= {self.token_limit} tokens)")
            # When called as middleware hook, return None so the agent state is
            # untouched (avoids duplicating messages via add_messages reducer).
            return None if runtime is not None else state

        # Compress messages
        original_token_count = self.count_tokens(messages)
        compressed_messages = self._compress_messages(messages)
        compressed_token_count = self.count_tokens(compressed_messages)

        logger.warning(
            f"Message compression executed (Issue #721): {original_token_count} -> {compressed_token_count} tokens "
            f"(limit: {self.token_limit}), {len(messages)} -> {len(compressed_messages)} messages"
        )

        # Ensure system messages are at position 0 (required by vLLM / Qwen)
        compressed_messages = _hoist_system_messages(compressed_messages)

        state["messages"] = compressed_messages
        return state

    def _compress_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Compress messages to fit within token limit through two strategies:
        1. First, compress web_search ToolMessage raw_content by truncating to 1024 chars
        2. If still over limit, drop oldest messages while preserving prefix messages and system messages
        
        Args:
            messages: List of messages to compress
        Returns:
            List of messages with compressed content and/or dropped messages
        """
        # Create a deep copy to avoid mutating original messages
        compressed = copy.deepcopy(messages)
        
        # Step 1: Compress raw_content in web_search ToolMessages
        for msg in compressed:
            # Only compress ToolMessage with name 'web_search'
            if isinstance(msg, ToolMessage) and getattr(msg, "name", None) == "web_search":
                try:
                    # Determine content type and check if compression is needed
                    if isinstance(msg.content, str):
                        # Early exit if content is small enough (avoid JSON parsing overhead)
                        # A heuristic: if string is less than 2KB, raw_content likely doesn't need truncation
                        if len(msg.content) < 2048:
                            continue
                        
                        try:
                            content_data = json.loads(msg.content)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse JSON content in web_search ToolMessage: {e}. Content: {msg.content[:200]}")
                            continue
                    elif isinstance(msg.content, list):
                        content_data = copy.deepcopy(msg.content)
                    else:
                        continue

                    # Compress raw_content in the content (item by item processing)
                    # Track if any modifications were made
                    modified = False
                    if isinstance(content_data, list):
                        for item in content_data:
                            if isinstance(item, dict) and "raw_content" in item:
                                raw_content = item.get("raw_content")
                                if raw_content and isinstance(raw_content, str) and len(raw_content) > 1024:
                                    item["raw_content"] = raw_content[:1024]
                                    modified = True
                        
                        # Update message content with modified data only if changes were made
                        if modified:
                            msg.content = json.dumps(content_data, ensure_ascii=False)
                except Exception as e:
                    logger.error(f"Unexpected error during message compression: {e}")
                    continue

        # Step 2: If still over limit after raw_content compression, drop oldest messages
        # while preserving prefix messages (e.g., system message) and recent messages.
        # We must keep AIMessage/ToolMessage pairs together — a ToolMessage without its
        # parent AIMessage (which carries the tool_call_id) causes vLLM to reject the
        # request.
        if self.is_over_limit(compressed):
            preserved_count = self.preserve_prefix_message_count
            preserved_messages = compressed[:preserved_count]
            remaining_messages = compressed[preserved_count:]

            # Build suffix by walking backwards, keeping recent messages.
            # Collect messages from the end until adding more would exceed the
            # token budget left after the preserved prefix.
            suffix: list[BaseMessage] = []
            for msg in reversed(remaining_messages):
                candidate = preserved_messages + [msg] + suffix
                if self.is_over_limit(candidate):
                    break
                suffix.insert(0, msg)

            # Safety: ensure we don't leave orphaned ToolMessages at the start
            # of the suffix (they need their preceding AIMessage with tool_calls).
            while suffix and isinstance(suffix[0], ToolMessage):
                suffix.pop(0)

            compressed = preserved_messages + suffix

        # Step 3: Verify that compression was successful and log warning if needed
        if self.is_over_limit(compressed):
            current_tokens = self.count_tokens(compressed)
            logger.warning(
                f"Message compression failed to bring tokens below limit: "
                f"{current_tokens} > {self.token_limit} tokens. "
                f"Total messages: {len(compressed)}. "
                f"Consider increasing token_limit or preserve_prefix_message_count."
            )

        return compressed

def validate_message_content(messages: List[BaseMessage], max_content_length: int = 100000) -> List[BaseMessage]:
    """
    Validate and fix all messages to ensure they have valid content before sending to LLM.
    
    This function ensures:
    1. All messages have a content field
    2. No message has None or empty string content (except for legitimate empty responses)
    3. Complex objects (lists, dicts) are converted to JSON strings
    4. Content is truncated if too long to prevent token overflow
    
    Args:
        messages: List of messages to validate
        max_content_length: Maximum allowed content length per message (default 100000)
    
    Returns:
        List of validated messages with fixed content
    """
    validated = []
    for i, msg in enumerate(messages):
        try:
            # Check if message has content attribute
            if not hasattr(msg, 'content'):
                logger.warning(f"Message {i} ({type(msg).__name__}) has no content attribute")
                msg.content = ""
            
            # Handle None content
            elif msg.content is None:
                logger.warning(f"Message {i} ({type(msg).__name__}) has None content, setting to empty string")
                msg.content = ""
            
            # Handle complex content types (convert to JSON)
            elif isinstance(msg.content, (list, dict)):
                logger.debug(f"Message {i} ({type(msg).__name__}) has complex content type {type(msg.content).__name__}, converting to JSON")
                msg.content = json.dumps(msg.content, ensure_ascii=False)
            
            # Handle other non-string types
            elif not isinstance(msg.content, str):
                logger.debug(f"Message {i} ({type(msg).__name__}) has non-string content type {type(msg.content).__name__}, converting to string")
                msg.content = str(msg.content)
            
            # Validate content length
            if isinstance(msg.content, str) and len(msg.content) > max_content_length:
                logger.warning(f"Message {i} content truncated from {len(msg.content)} to {max_content_length} chars")
                msg.content = msg.content[:max_content_length].rstrip() + "..."
            
            validated.append(msg)
        except Exception as e:
            logger.error(f"Error validating message {i}: {e}")
            # Create a safe fallback message
            if isinstance(msg, ToolMessage):
                msg.content = json.dumps({"error": str(e)}, ensure_ascii=False)
            else:
                msg.content = f"[Error processing message: {str(e)}]"
            validated.append(msg)
    
    return validated

