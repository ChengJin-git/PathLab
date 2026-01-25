"""
LLM 客户端：仅对接本地 vLLM（OpenAI 兼容）。
Key/URL/模型 从 backend.agent.api_keys 读取，见 api_keys.env.example。
"""
from langchain_openai import ChatOpenAI

from . import api_keys


def get_llm(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> ChatOpenAI:
    """
    使用本地 vLLM 构建 ChatOpenAI。
    参数优先；否则从 api_keys（环境变量 / backend/agent/.env）读取。
    """
    base = (base_url or api_keys.vllm_url()).rstrip("/")
    key = api_key or api_keys.vllm_key()
    mdl = model or api_keys.vllm_model()
    max_tokens = api_keys.vllm_max_tokens() or 8192

    return ChatOpenAI(
        base_url=base,
        api_key=key,
        model=mdl,
        temperature=0.7,
        max_tokens=max_tokens,
        streaming=True,
        stream_usage=True,
    )
