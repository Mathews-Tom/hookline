"""Knowledge base manager: intent processing and context retrieval."""
from __future__ import annotations

from typing import Any

from hookline.memory.intents import extract_tags, parse_intent
from hookline.memory.store import MemoryStore


class KnowledgeManager:
    """Processes messages for intents and manages the knowledge base."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def process_message(
        self,
        project: str,
        sender: str,
        text: str,
    ) -> dict[str, Any] | None:
        """Process a message: log it, extract intents, update knowledge.

        Returns a dict describing the action taken, or None for plain messages.
        """
        intent, tag_content, clean_text = parse_intent(text)
        tags = extract_tags(text)

        msg_id = self._store.log_message(
            project=project,
            sender=sender,
            text=clean_text or text,
            intent=intent,
        )

        if intent == "remember":
            fact_text = tag_content or clean_text
            kid = self._store.log_knowledge(project, "fact", fact_text, source_id=msg_id)
            return {"action": "remember", "knowledge_id": kid, "text": fact_text, "tags": tags}

        if intent == "goal":
            goal_text = tag_content or clean_text
            kid = self._store.log_knowledge(project, "goal", goal_text, source_id=msg_id)
            return {"action": "goal", "knowledge_id": kid, "text": goal_text, "tags": tags}

        if intent == "done":
            done_text = tag_content or clean_text
            goals = self._store.get_knowledge(project, category="goal", active_only=True)
            deactivated: list[int] = []
            for goal in goals:
                if done_text.lower() in goal["text"].lower():
                    self._store.deactivate_knowledge(goal["id"])
                    deactivated.append(goal["id"])
            return {"action": "done", "deactivated": deactivated, "query": done_text, "tags": tags}

        return None

    def get_context(self, project: str, limit: int = 20) -> dict[str, Any]:
        """Return a context snapshot: recent messages, goals, facts."""
        return {
            "recent_messages": self._store.get_messages(project, limit=limit),
            "active_goals": self._store.get_knowledge(project, category="goal", active_only=True),
            "facts": self._store.get_knowledge(project, category="fact", active_only=True),
            "preferences": self._store.get_knowledge(
                project, category="preference", active_only=True,
            ),
        }

    def remember(self, project: str, text: str, category: str = "fact") -> int:
        """Directly add a knowledge entry."""
        return self._store.log_knowledge(project, category, text)

    def recall(self, project: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search messages and knowledge by query text."""
        return self._store.search_messages(project, query, limit=limit)

    def forget(self, project: str, knowledge_id: int) -> bool:  # noqa: ARG002
        """Deactivate a knowledge entry."""
        return self._store.deactivate_knowledge(knowledge_id)
