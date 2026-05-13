from backend.core import memory


def test_save_retrieve_search_and_build_context(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")

    memory.save_exchange(
        "session-1",
        "Find remote QA jobs",
        "Found 3 remote QA jobs.",
        "search_web",
    )
    memory.save_message("session-1", "user", "Add expense for lunch", "save_data")

    history = memory.get_history("session-1", limit=3)
    assert [msg["role"] for msg in history] == ["user", "assistant", "user"]
    assert history[0]["content"] == "Find remote QA jobs"

    results = memory.search_memory("session-1", "expense")
    assert len(results) == 1
    assert results[0]["content"] == "Add expense for lunch"

    context = memory.build_context("session-1", "What did I search for?")
    assert "Recent conversation:" in context
    assert "You: Find remote QA jobs" in context
    assert "AI: Found 3 remote QA jobs." in context

    semantic_hits = memory.search_semantic_memory("session-1", "remote jobs")
    assert semantic_hits
    assert semantic_hits[0]["score"] > 0


def test_cleanup_older_than_removes_old_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory-retention.db")
    memory.save_message("session-1", "user", "old note")
    with memory._get_conn() as conn:
        conn.execute("UPDATE conversation_memory SET created_at = datetime('now', '-10 days')")
        conn.execute("UPDATE semantic_memory SET created_at = datetime('now', '-10 days')")
        conn.commit()

    deleted = memory.cleanup_older_than(5)

    assert deleted["conversation_memory"] == 1
    assert deleted["semantic_memory"] == 1
    assert memory.get_history("session-1") == []
