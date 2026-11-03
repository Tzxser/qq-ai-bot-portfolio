from typing import Protocol


class LongTermMemory(Protocol):
    """Future opt-in memory adapter; no long-term extraction in v1."""
    async def recall(self, conversation_key: str, query: str) -> list[str]: ...


class NoMemory:
    async def recall(self, conversation_key, query):
        return []
