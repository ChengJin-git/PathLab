"""
PathLab Agent — 统一读取 API Key 与相关配置。

- 优先从环境变量读取；导入时若存在 `backend/agent/.env` 则用 python-dotenv 加载
  （不覆盖已有环境变量）。
- 勿将真实 key 写入代码库；本地密钥放在 `backend/agent/.env`（已加入 .gitignore）。
- 变量模板见 `api_keys.env.example`。
"""
import os
from pathlib import Path

_AGENT_DIR = Path(__file__).resolve().parent
_ENV_FILE = _AGENT_DIR / ".env"

try:
    from dotenv import load_dotenv
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, override=False)
except ImportError:
    pass

# --- 默认值（仅用于本地 vLLM 等无需真实 key 的场景）---
DEFAULT_VLLM_URL = "http://localhost:8000/v1"
DEFAULT_VLLM_KEY = "sk-pathlab"
DEFAULT_VLLM_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"


def vllm_url(default: str | None = DEFAULT_VLLM_URL) -> str | None:
    return os.environ.get("VLLM_URL") or default


def vllm_key(default: str | None = DEFAULT_VLLM_KEY) -> str | None:
    return os.environ.get("VLLM_KEY") or default


def vllm_model(default: str | None = DEFAULT_VLLM_MODEL) -> str | None:
    return os.environ.get("VLLM_MODEL") or default


def vllm_max_tokens() -> int | None:
    v = os.environ.get("VLLM_MAX_TOKENS")
    return int(v) if (v and v.isdigit()) else None


def tavily_api_key() -> str | None:
    return os.environ.get("TAVILY_API_KEY")


def openai_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY")


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def google_api_key() -> str | None:
    return os.environ.get("GOOGLE_API_KEY")


def langsmith_api_key() -> str | None:
    return os.environ.get("LANGSMITH_API_KEY")


def get_all(which: str = "vllm") -> dict[str, str | int | None]:
    """方便批量取键。which: 'vllm' | 'tavily' | 'llm_providers' | 'all'."""
    out: dict[str, str | int | None] = {}
    if which in ("vllm", "all"):
        out["VLLM_URL"] = vllm_url()
        out["VLLM_KEY"] = vllm_key()
        out["VLLM_MODEL"] = vllm_model()
        out["VLLM_MAX_TOKENS"] = vllm_max_tokens()
    if which in ("tavily", "all"):
        out["TAVILY_API_KEY"] = tavily_api_key()
    if which in ("llm_providers", "all"):
        out["OPENAI_API_KEY"] = openai_api_key()
        out["ANTHROPIC_API_KEY"] = anthropic_api_key()
        out["GOOGLE_API_KEY"] = google_api_key()
    if which == "all":
        out["LANGSMITH_API_KEY"] = langsmith_api_key()
    return out
