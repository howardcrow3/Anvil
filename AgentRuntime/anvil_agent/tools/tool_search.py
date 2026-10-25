"""Progressive tool disclosure: ``tool_search`` / ``tool_describe`` / ``tool_call``.

Adapted from Hermes Agent's ``tools/tool_search*.py`` (MIT, Nous Research; see THIRD_PARTY_NOTICES.md).
Deferred tools are removed from the per-request tool schema list and reached through three bridge
tools, which roughly halves the schema cost on small local models. The deferred catalog is
stateless (rebuilt from the registry on demand) and the listing embedded in ``tool_search``'s
description is sorted, so it is byte-stable and prompt-cache friendly.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Any

from anvil_agent.models.types import ToolCallRequest, ToolResult

if TYPE_CHECKING:
    from anvil_agent.tools.registry import ToolRegistry

MAX_QUERIES_PER_CALL = 7
MAX_DESCRIBE_NAMES = 10
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _stem(word: str) -> str:
    """Tiny suffix stemmer: enough that 'issues' matches 'create_issue' and 'fetching' matches 'fetch'."""
    w = word.lower()
    for suffix in ("ing", "ed"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            w = w[: -len(suffix)]
            break
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN_RE.findall(text or "")]


def _short_desc(description: str, max_chars: int = 80) -> str:
    text = " ".join((description or "").split())
    m = _SENTENCE_END.search(text)
    if m:
        text = text[: m.end()]
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0]
    return clipped.rstrip(",;: ") + "…"


def _param_summary(schema: dict[str, Any]) -> dict[str, str]:
    props = (schema.get("parameters") or {}).get("properties") or {}
    required = set((schema.get("parameters") or {}).get("required") or [])
    return {
        k: f"{v.get('type', 'any')}{'' if k in required else '?'}" for k, v in props.items()
    }


class _Doc:
    __slots__ = ("name", "schema", "tokens")

    def __init__(self, name: str, schema: dict[str, Any]) -> None:
        self.name = name
        self.schema = schema
        words = re.sub(r"[_.:\-]", " ", name)
        params = " ".join(((schema.get("parameters") or {}).get("properties") or {}).keys())
        self.tokens = tokenize(f"{words} {words} {schema.get('description', '')} {params}")


def _bm25(query: list[str], doc: _Doc, df: Counter, n: int, avg: float, k1: float = 1.5, b: float = 0.75) -> float:
    tf = Counter(doc.tokens)
    dl = len(doc.tokens) or 1
    score = 0.0
    for t in set(query):
        if t not in tf:
            continue
        idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
        score += idf * (tf[t] * (k1 + 1)) / (tf[t] + k1 * (1 - b + b * dl / avg))
    return score


def search_docs(docs: list[_Doc], query: str, limit: int = 5) -> list[_Doc]:
    """Top-``limit`` docs for ``query`` by BM25; an exact tool-name match always ranks first."""
    q = tokenize(query)
    exact = query.strip().lower()
    if not docs or not q:
        return []
    df: Counter = Counter()
    for d in docs:
        df.update(set(d.tokens))
    avg = sum(len(d.tokens) for d in docs) / len(docs) or 1.0
    answerable = {t for t in q if df[t] > 0}
    need = 1 if len(answerable) < 3 else math.ceil(len(answerable) / 2)
    scored: list[tuple[float, _Doc]] = []
    for d in docs:
        if d.name.lower() == exact:
            scored.append((float("inf"), d))
            continue
        if len(answerable & set(d.tokens)) < need:
            continue
        s = _bm25(q, d, df, len(docs), avg)
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [d for _, d in scored[:limit]]


class ToolSearchBridge:
    def __init__(self, registry: "ToolRegistry", listing_max_chars: int = 6000, default_limit: int = 5, max_limit: int = 25) -> None:
        self._registry = registry
        self._listing_max = listing_max_chars
        self._default_limit = default_limit
        self._max_limit = max_limit

    # -- catalog --------------------------------------------------------------

    def _docs(self) -> list[_Doc]:
        out = []
        for name in self._registry.deferred_names:
            tool = self._registry.get(name)
            if tool is not None:
                out.append(_Doc(name, tool.to_schema()))
        return out

    def listing(self) -> str:
        """Sorted, budgeted catalog embedded in the tool_search description: full → names → bare."""
        docs = sorted(self._docs(), key=lambda d: d.name)
        full = "\n".join(f"- {d.name}: {_short_desc(d.schema.get('description', ''))}" for d in docs)
        if len(full) <= self._listing_max:
            return full
        names = ", ".join(d.name for d in docs)
        return names if len(names) <= self._listing_max else ""

    def schemas(self) -> list[dict[str, Any]]:
        listing = self.listing()
        catalog = f"\n\nDeferred tools available through this bridge:\n{listing}" if listing else ""
        return [
            {
                "name": "tool_search",
                "description": "Find additional tools by what you want to do. Returns matching tool names, "
                "descriptions and parameter names. Use tool_call to run one." + catalog,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queries": {"type": "array", "items": {"type": "string"}, "description": "One or more short search phrases."},
                        "limit": {"type": "integer", "description": f"Max matches per query (default {self._default_limit})."},
                    },
                    "required": ["queries"],
                },
            },
            {
                "name": "tool_describe",
                "description": "Get the full JSON schema for one or more deferred tools before calling them.",
                "parameters": {
                    "type": "object",
                    "properties": {"names": {"type": "array", "items": {"type": "string"}}},
                    "required": ["names"],
                },
            },
            {
                "name": "tool_call",
                "description": "Run a deferred tool by name with its arguments object.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Deferred tool name."},
                        "arguments": {"type": "object", "description": "Arguments for that tool."},
                    },
                    "required": ["name", "arguments"],
                },
            },
        ]

    # -- dispatch -------------------------------------------------------------

    async def handle(self, request: ToolCallRequest) -> ToolResult:
        args = request.arguments
        if request.name == "tool_search":
            return self._ok(request, self._search(args))
        if request.name == "tool_describe":
            return self._describe(request, args)
        return await self._call(request, args)

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        queries = args.get("queries") or ([args["query"]] if isinstance(args.get("query"), str) else [])
        if isinstance(queries, str):
            queries = [queries]
        queries = [q for q in queries if isinstance(q, str) and q.strip()][:MAX_QUERIES_PER_CALL]
        try:
            limit = max(1, min(self._max_limit, int(args.get("limit", self._default_limit))))
        except (TypeError, ValueError):
            limit = self._default_limit
        docs = self._docs()
        results = []
        for q in queries:
            matches = search_docs(docs, q, limit)
            results.append({
                "query": q,
                "matches": [
                    {"name": d.name, "description": _short_desc(d.schema.get("description", ""), 160), "parameters": _param_summary(d.schema)}
                    for d in matches
                ],
                **({} if matches else {"hint": "No match. Try a simpler phrase or one key word."}),
            })
        return {"results": results}

    def _describe(self, request: ToolCallRequest, args: dict[str, Any]) -> ToolResult:
        names = args.get("names") or []
        if isinstance(names, str):
            names = [names]
        out, missing = {}, []
        for n in names[:MAX_DESCRIBE_NAMES]:
            tool = self._registry.get(n) if isinstance(n, str) else None
            if tool is None or n not in self._registry.deferred_names:
                missing.append(n)
            else:
                out[n] = tool.to_schema()
        payload: dict[str, Any] = {"schemas": out}
        if missing:
            payload["not_deferred_or_unknown"] = missing
        return self._ok(request, payload, is_error=not out and bool(missing))

    async def _call(self, request: ToolCallRequest, args: dict[str, Any]) -> ToolResult:
        name, inner = args.get("name"), args.get("arguments", {})
        if not isinstance(name, str) or not isinstance(inner, dict):
            return ToolResult(id=request.id, content="tool_call needs {name: string, arguments: object}.", is_error=True)
        if name not in self._registry.deferred_names:
            hint = "call it directly." if self._registry.get(name) else "use tool_search to find the right name."
            return ToolResult(id=request.id, content=f"'{name}' is not a deferred tool; {hint}", is_error=True)
        result = await self._registry.get(name).execute(inner)  # type: ignore[union-attr]
        result.id = request.id
        return result

    @staticmethod
    def _ok(request: ToolCallRequest, payload: dict[str, Any], is_error: bool = False) -> ToolResult:
        return ToolResult(id=request.id, content=json.dumps(payload, indent=1), is_error=is_error)
