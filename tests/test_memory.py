"""Tests for hookline memory subsystem: store, intents, search, knowledge, commands."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# ── Store Tests ──────────────────────────────────────────────────────────────


class TestMemoryStore:
    """Tests for hookline.memory.store.MemoryStore."""

    def test_create_store_creates_tables(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        db = tmp_path / "test.db"
        with MemoryStore(db) as store:
            stats = store.get_stats("proj")
            assert stats == {"messages": 0, "knowledge": 0}

    def test_log_message_returns_id(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            mid = store.log_message("proj", "user", "hello world")
            assert isinstance(mid, int)
            assert mid >= 1

    def test_get_messages_filters_by_project(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            store.log_message("proj-a", "user", "msg a")
            store.log_message("proj-b", "user", "msg b")
            msgs = store.get_messages("proj-a")
            assert len(msgs) == 1
            assert msgs[0]["text"] == "msg a"

    def test_get_messages_with_limit(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            for i in range(10):
                store.log_message("proj", "user", f"msg {i}")
            msgs = store.get_messages("proj", limit=3)
            assert len(msgs) == 3

    def test_get_messages_by_sender(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            store.log_message("proj", "alice", "from alice")
            store.log_message("proj", "bob", "from bob")
            msgs = store.get_messages("proj", sender="alice")
            assert len(msgs) == 1
            assert msgs[0]["sender"] == "alice"

    def test_log_knowledge_and_retrieve(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            kid = store.log_knowledge("proj", "fact", "Python is great")
            assert isinstance(kid, int)
            entries = store.get_knowledge("proj", category="fact")
            assert len(entries) == 1
            assert entries[0]["text"] == "Python is great"

    def test_deactivate_knowledge(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            kid = store.log_knowledge("proj", "goal", "finish the task")
            assert store.deactivate_knowledge(kid) is True
            active = store.get_knowledge("proj", category="goal", active_only=True)
            assert len(active) == 0
            all_entries = store.get_knowledge("proj", category="goal", active_only=False)
            assert len(all_entries) == 1

    def test_deactivate_nonexistent_returns_false(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            assert store.deactivate_knowledge(9999) is False

    def test_search_messages_by_text(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            store.log_message("proj", "user", "the quick brown fox")
            store.log_message("proj", "user", "lazy dog sleeps")
            results = store.search_messages("proj", "quick")
            assert len(results) == 1
            assert "quick" in results[0]["text"]

    def test_get_stats(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            store.log_message("proj", "user", "msg1")
            store.log_message("proj", "user", "msg2")
            store.log_knowledge("proj", "fact", "a fact")
            stats = store.get_stats("proj")
            assert stats["messages"] == 2
            assert stats["knowledge"] == 1

    def test_context_manager_protocol(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            store.log_message("proj", "user", "test")
        # After exit, connection should be closed — operations should fail
        with pytest.raises(Exception):
            store.log_message("proj", "user", "should fail")

    def test_get_store_singleton(
        self, hookline: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.memory import store as store_mod
        monkeypatch.setattr(store_mod, "_store_instance", None)
        s1 = store_mod.get_store()
        s2 = store_mod.get_store()
        assert s1 is s2
        s1.close()
        monkeypatch.setattr(store_mod, "_store_instance", None)


# ── Intents Tests ────────────────────────────────────────────────────────────


class TestIntents:
    """Tests for hookline.memory.intents."""

    def test_parse_no_intent(self, hookline: Any) -> None:
        from hookline.memory.intents import parse_intent
        intent, content, clean = parse_intent("just a normal message")
        assert intent == ""
        assert content == ""
        assert clean == "just a normal message"

    def test_parse_remember_tag(self, hookline: Any) -> None:
        from hookline.memory.intents import parse_intent
        intent, content, clean = parse_intent("[REMEMBER] always use uv")
        assert intent == "remember"
        assert content == ""
        assert clean == "always use uv"

    def test_parse_remember_with_content(self, hookline: Any) -> None:
        from hookline.memory.intents import parse_intent
        intent, content, clean = parse_intent("[REMEMBER: prefer dark mode] settings")
        assert intent == "remember"
        assert content == "prefer dark mode"
        assert "settings" in clean

    def test_parse_goal_tag(self, hookline: Any) -> None:
        from hookline.memory.intents import parse_intent
        intent, content, clean = parse_intent("[GOAL] finish the auth module")
        assert intent == "goal"
        assert clean == "finish the auth module"

    def test_parse_done_tag(self, hookline: Any) -> None:
        from hookline.memory.intents import parse_intent
        intent, content, clean = parse_intent("[DONE] auth module")
        assert intent == "done"
        assert clean == "auth module"

    def test_tags_case_insensitive(self, hookline: Any) -> None:
        from hookline.memory.intents import parse_intent
        intent, _, _ = parse_intent("[remember] something")
        assert intent == "remember"
        intent2, _, _ = parse_intent("[Goal] something else")
        assert intent2 == "goal"

    def test_extract_hashtags(self, hookline: Any) -> None:
        from hookline.memory.intents import extract_tags
        tags = extract_tags("working on #auth and #security features")
        assert "auth" in tags
        assert "security" in tags

    def test_extract_hashtags_min_length(self, hookline: Any) -> None:
        from hookline.memory.intents import extract_tags
        tags = extract_tags("tag #a and #ab and #abc")
        assert "a" not in tags
        assert "ab" in tags
        assert "abc" in tags


# ── TF-IDF Search Tests ─────────────────────────────────────────────────────


class TestTfIdfSearcher:
    """Tests for hookline.memory.search.TfIdfSearcher."""

    def test_add_and_search_documents(self, hookline: Any) -> None:
        from hookline.memory.search import TfIdfSearcher
        searcher = TfIdfSearcher()
        searcher.add_document(1, "python programming language")
        searcher.add_document(2, "javascript web development")
        searcher.add_document(3, "python data science analysis")
        results = searcher.search("python programming")
        assert len(results) > 0
        assert results[0][0] == 1

    def test_search_relevance_ordering(self, hookline: Any) -> None:
        from hookline.memory.search import TfIdfSearcher
        searcher = TfIdfSearcher()
        searcher.add_document(1, "python flask web application deployment server")
        searcher.add_document(2, "python machine learning neural network training")
        searcher.add_document(3, "javascript react frontend components")
        searcher.add_document(4, "rust systems programming memory safety")
        results = searcher.search("python flask deployment")
        assert len(results) >= 1
        # Doc 1 is the best match for flask + deployment
        assert results[0][0] == 1

    def test_search_empty_corpus(self, hookline: Any) -> None:
        from hookline.memory.search import TfIdfSearcher
        searcher = TfIdfSearcher()
        results = searcher.search("anything")
        assert results == []

    def test_search_no_matching_terms(self, hookline: Any) -> None:
        from hookline.memory.search import TfIdfSearcher
        searcher = TfIdfSearcher()
        searcher.add_document(1, "python programming")
        results = searcher.search("xylophone")
        assert results == []

    def test_tokenize_strips_punctuation(self, hookline: Any) -> None:
        from hookline.memory.search import tokenize
        tokens = tokenize("Hello, World! This is a test.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_stopwords_filtered(self, hookline: Any) -> None:
        from hookline.memory.search import tokenize
        tokens = tokenize("the quick brown fox is very fast")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "very" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens

    def test_clear_removes_all(self, hookline: Any) -> None:
        from hookline.memory.search import TfIdfSearcher
        searcher = TfIdfSearcher()
        searcher.add_document(1, "test document")
        searcher.clear()
        results = searcher.search("test")
        assert results == []


# ── Knowledge Manager Tests ──────────────────────────────────────────────────


class TestKnowledgeManager:
    """Tests for hookline.memory.knowledge.KnowledgeManager."""

    def test_process_plain_message(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            result = km.process_message("proj", "user", "just chatting")
            assert result is None
            msgs = store.get_messages("proj")
            assert len(msgs) == 1

    def test_process_remember_creates_fact(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            result = km.process_message("proj", "user", "[REMEMBER] always use uv")
            assert result is not None
            assert result["action"] == "remember"
            facts = store.get_knowledge("proj", category="fact")
            assert len(facts) == 1
            assert "always use uv" in facts[0]["text"]

    def test_process_goal_creates_goal(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            result = km.process_message("proj", "user", "[GOAL] finish auth module")
            assert result is not None
            assert result["action"] == "goal"
            goals = store.get_knowledge("proj", category="goal")
            assert len(goals) == 1

    def test_process_done_deactivates_goal(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            km.process_message("proj", "user", "[GOAL] finish auth module")
            result = km.process_message("proj", "user", "[DONE] auth module")
            assert result is not None
            assert result["action"] == "done"
            assert len(result["deactivated"]) >= 1
            active_goals = store.get_knowledge("proj", category="goal", active_only=True)
            assert len(active_goals) == 0

    def test_get_context_includes_all_categories(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            km.process_message("proj", "user", "[REMEMBER] a fact")
            km.process_message("proj", "user", "[GOAL] a goal")
            km.process_message("proj", "user", "plain msg")
            ctx = km.get_context("proj")
            assert "recent_messages" in ctx
            assert "active_goals" in ctx
            assert "facts" in ctx
            assert "preferences" in ctx
            assert len(ctx["recent_messages"]) == 3
            assert len(ctx["active_goals"]) == 1
            assert len(ctx["facts"]) == 1

    def test_remember_directly(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            kid = km.remember("proj", "direct fact")
            assert isinstance(kid, int)
            facts = store.get_knowledge("proj", category="fact")
            assert len(facts) == 1

    def test_recall_searches(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            store.log_message("proj", "user", "python is great for scripting")
            store.log_message("proj", "user", "javascript for web")
            results = km.recall("proj", "python")
            assert len(results) == 1
            assert "python" in results[0]["text"]

    def test_forget_deactivates(self, hookline: Any, tmp_path: Path) -> None:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import MemoryStore
        with MemoryStore(tmp_path / "test.db") as store:
            km = KnowledgeManager(store)
            kid = km.remember("proj", "something to forget")
            assert km.forget("proj", kid) is True
            assert km.forget("proj", kid) is False


# ── Memory Command Tests ─────────────────────────────────────────────────────


class TestMemoryCommands:
    """Tests for memory commands registered in hookline.commands."""

    def test_remember_command(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "MEMORY_ENABLED", True)

        from hookline.memory import store as store_mod
        monkeypatch.setattr(store_mod, "_store_instance", None)
        db_path = str(tmp_path / "hookline-state" / "memory.db")
        _config = sys.modules["hookline.config"]
        monkeypatch.setattr(_config, "MEMORY_DB_PATH", db_path)

        assert dispatch("remember", "test-proj", "always use uv", 1)
        assert len(mock_telegram) == 1
        assert "Stored" in mock_telegram[0][1]["text"]

    def test_recall_command(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "MEMORY_ENABLED", True)

        from hookline.memory import store as store_mod
        monkeypatch.setattr(store_mod, "_store_instance", None)
        db_path = str(tmp_path / "hookline-state" / "memory.db")
        _config = sys.modules["hookline.config"]
        monkeypatch.setattr(_config, "MEMORY_DB_PATH", db_path)

        # Seed a message
        from hookline.memory.store import MemoryStore
        with MemoryStore(db_path) as store:
            store.log_message("test-proj", "user", "python is wonderful for scripting")

        monkeypatch.setattr(store_mod, "_store_instance", None)
        assert dispatch("recall", "test-proj", "python", 1)
        assert len(mock_telegram) == 1
        assert "Recall" in mock_telegram[0][1]["text"]

    def test_goals_command(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "MEMORY_ENABLED", True)

        from hookline.memory import store as store_mod
        monkeypatch.setattr(store_mod, "_store_instance", None)
        db_path = str(tmp_path / "hookline-state" / "memory.db")
        _config = sys.modules["hookline.config"]
        monkeypatch.setattr(_config, "MEMORY_DB_PATH", db_path)

        # Seed a goal
        from hookline.memory.store import MemoryStore
        with MemoryStore(db_path) as store:
            store.log_knowledge("test-proj", "goal", "finish auth module")

        monkeypatch.setattr(store_mod, "_store_instance", None)
        assert dispatch("goals", "test-proj", "", 1)
        assert len(mock_telegram) == 1
        assert "Goals" in mock_telegram[0][1]["text"]

    def test_context_command(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "MEMORY_ENABLED", True)

        from hookline.memory import store as store_mod
        monkeypatch.setattr(store_mod, "_store_instance", None)
        db_path = str(tmp_path / "hookline-state" / "memory.db")
        _config = sys.modules["hookline.config"]
        monkeypatch.setattr(_config, "MEMORY_DB_PATH", db_path)

        # Seed data
        from hookline.memory.store import MemoryStore
        with MemoryStore(db_path) as store:
            store.log_message("test-proj", "user", "a message")
            store.log_knowledge("test-proj", "fact", "a fact")

        monkeypatch.setattr(store_mod, "_store_instance", None)
        assert dispatch("context", "test-proj", "", 1)
        assert len(mock_telegram) == 1
        assert "Context" in mock_telegram[0][1]["text"]

    def test_forget_command(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "MEMORY_ENABLED", True)

        from hookline.memory import store as store_mod
        monkeypatch.setattr(store_mod, "_store_instance", None)
        db_path = str(tmp_path / "hookline-state" / "memory.db")
        _config = sys.modules["hookline.config"]
        monkeypatch.setattr(_config, "MEMORY_DB_PATH", db_path)

        # Seed a knowledge entry
        from hookline.memory.store import MemoryStore
        with MemoryStore(db_path) as store:
            kid = store.log_knowledge("test-proj", "fact", "something")

        monkeypatch.setattr(store_mod, "_store_instance", None)
        assert dispatch("forget", "test-proj", str(kid), 1)
        assert len(mock_telegram) == 1
        assert "Deactivated" in mock_telegram[0][1]["text"]

    def test_memory_commands_disabled_when_not_enabled(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        # MEMORY_ENABLED should be False by default (from conftest patches)

        assert dispatch("remember", "proj", "some text", 1)
        assert len(mock_telegram) == 1
        assert "disabled" in mock_telegram[0][1]["text"].lower()

    def test_forget_invalid_id(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "MEMORY_ENABLED", True)

        assert dispatch("forget", "proj", "not-a-number", 1)
        assert "number" in mock_telegram[0][1]["text"].lower()

    def test_remember_no_args(
        self,
        hookline: Any,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.commands import dispatch
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "MEMORY_ENABLED", True)

        assert dispatch("remember", "proj", "", 1)
        assert "Usage" in mock_telegram[0][1]["text"]
