"""JSON-RPC 2.0 message types."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: str = "2.0"
    result: Any = None
    error: JsonRpcError | None = None
    id: str | int | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error."""

    code: int
    message: str
    data: Any = None


class JsonRpcNotification(BaseModel):
    """JSON-RPC 2.0 notification (no id, no response expected)."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


# Standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
