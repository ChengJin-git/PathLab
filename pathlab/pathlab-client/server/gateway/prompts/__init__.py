"""
Prompt templates for PathLab Agent.
"""
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """
    Load a prompt template from file.

    Args:
        name: Name of the prompt file (without .txt extension)

    Returns:
        The prompt content as string
    """
    prompt_path = PROMPTS_DIR / f"{name}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def get_chat_system_prompt() -> str:
    """
    Get the PathLab Agent system prompt for chat.

    Returns:
        The full system prompt content
    """
    return load_prompt("chat_system_prompt")

