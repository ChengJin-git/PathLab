from pathlib import Path

from gateway.knowledge import chat as chat_knowledge


def test_bundled_training_runtime_dirs_live_under_gateway_knowledge():
    cache_dir = chat_knowledge.get_training_rag_cache_dir()
    vector_dir = chat_knowledge.get_training_rag_vectorstore_dir()
    runtime_dir = chat_knowledge.get_training_rag_runtime_dir()

    assert runtime_dir == chat_knowledge.CHAT_KNOWLEDGE_DIR / "training_rag"
    assert cache_dir == runtime_dir / "cache"
    assert vector_dir == runtime_dir / "vector_store"
    assert cache_dir.is_dir()
    assert vector_dir.is_dir()


def test_bundled_training_papers_stay_in_source_tree():
    assert isinstance(chat_knowledge.TRAINING_PAPERS_DIR, Path)
    assert chat_knowledge.TRAINING_PAPERS_DIR.name == "papers"
