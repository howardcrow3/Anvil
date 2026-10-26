"""Web fetch tool."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


MAX_REDIRECTS = 5


async def check_public_url(url: str) -> str | None:
    """None if ``url`` is an http(s) URL that only resolves to public addresses, else the reason it is refused.

    web_fetch runs without approval, so it must not reach loopback, private-network, link-local or cloud
    metadata addresses (169.254.169.254): a prompt-injected page could otherwise read them or smuggle data
    out in a query string. Limitation: the name is resolved again when the connection is made, so a
    hostile DNS server that changes its answer between the two lookups is not covered.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return "invalid URL"
    if parts.scheme not in ("http", "https") or not host:
        return "only http(s) URLs are allowed"
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        return f"cannot resolve {host}: {e}"
    for info in infos:
        addr = info[4][0].split("%")[0]
        try:
            if not ipaddress.ip_address(addr).is_global:
                return f"{host} resolves to a non-public address ({addr})"
        except ValueError:
            return f"unrecognised address {addr}"
    return None


class WebFetchTool(Tool):

    defer = True
    name = "web_fetch"
    description = "Fetch a web page and return its text content."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url")
        if not isinstance(url, str) or not url:
            return ToolResult(id="", content="Error: 'url' is required", is_error=True)

        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
                # Follow redirects ourselves so every hop is checked, not just the first URL.
                for _ in range(MAX_REDIRECTS + 1):
                    refused = await check_public_url(url)
                    if refused:
                        return ToolResult(id="", content=f"Error: refusing to fetch {url}: {refused}", is_error=True)
                    resp = await client.get(url)
                    if resp.is_redirect and resp.headers.get("location"):
                        url = urljoin(url, resp.headers["location"])
                        continue
                    break
                else:
                    return ToolResult(id="", content=f"Error: more than {MAX_REDIRECTS} redirects", is_error=True)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "html" in content_type:
                    text = self._strip_html(resp.text)
                else:
                    text = resp.text

                if len(text) > 50000:
                    text = text[:50000] + "\n... (truncated)"

                return ToolResult(id="", content=text)
        except Exception as e:
            return ToolResult(id="", content=f"Error fetching URL: {e}", is_error=True)

    def _strip_html(self, html: str) -> str:
        """Basic HTML to text conversion."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
