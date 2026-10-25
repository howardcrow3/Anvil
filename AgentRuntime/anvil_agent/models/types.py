"""Shared types for model providers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """A request from the model to call a tool."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of executing a tool."""

    id: str
    content: str
    is_error: bool = False


class ChatMessage(BaseModel):
    """A message in the conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str = ""
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    tool_call_id: str | None = None


class ChatChunk(BaseModel):
    """A streaming chunk from the model."""

    delta_text: str = ""
    tool_call_delta: ToolCallDelta | None = None
    finish_reason: str | None = None


class ToolCallDelta(BaseModel):
    """Incremental tool call data in a streaming chunk."""

    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""
