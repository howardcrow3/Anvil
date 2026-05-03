"""Abstract base class for platform adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable


class PlatformAdapter(ABC):
    """Base class for all messaging platform adapters."""

    def __init__(self) -> None:
        self.on_message: Callable[[str, str, str], Awaitable[str]] | None = None
        self._running = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Platform name identifier."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the adapter."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the adapter gracefully."""
        ...

    @abstractmethod
    async def send_response(self, user_id: str, text: str) -> None:
        """Send a response message to a user."""
        ...

    @property
    def is_running(self) -> bool:
        """Whether the adapter is currently running."""
        return self._running
