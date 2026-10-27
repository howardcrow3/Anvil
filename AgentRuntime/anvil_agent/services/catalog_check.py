"""Checks the model catalog against Hugging Face: does each repo exist, does it have a usable GGUF, and is
``min_ram_gb`` plausible for the size of what would actually be downloaded?

    python -m anvil_agent.services.catalog_check          # needs network; set HF_TOKEN for gated repos

The assessment itself (``assess``) is pure so it can be tested offline. CI runs the real check on a schedule
(`.github/workflows/catalog-check.yml`) because the repos can change or disappear without any commit here.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx

from .llama_cpp_service import HF_BASE, LlamaCppError, select_gguf_files
from .model_catalog import MODEL_CATALOG, ModelCatalogEntry

GIB = 1024**3
# Weights are memory-mapped, but the OS, KV cache and the app itself need room on top of them.
MIN_HEADROOM = 1.10


@dataclass
class Assessment:
    entry: ModelCatalogEntry
    errors: list[str] = field(default_factory=list)  # the model cannot be downloaded/used as catalogued
    warnings: list[str] = field(default_factory=list)  # runs, but the catalog text is off
    quant_used: str | None = None
    download_gb: float | None = None

    @property
    def level(self) -> str:
        return "error" if self.errors else "warning" if self.warnings else "ok"

    @property
    def suggested_min_ram_gb(self) -> int | None:
        return None if self.download_gb is None else math.ceil(self.download_gb * MIN_HEADROOM)


def assess(entry: ModelCatalogEntry, tree: list[dict[str, Any]]) -> Assessment:
    """Judge one catalog entry against its repository's file listing."""
    result = Assessment(entry)
    try:
        quant, files = select_gguf_files(tree, entry.quant)
    except LlamaCppError as exc:
        result.errors.append(str(exc))
        return result
    result.quant_used = quant
    result.download_gb = round(sum(int(f.get("size") or 0) for f in files) / GIB, 1)
    if quant.lower() != entry.quant.lower():
        result.warnings.append(f"repo has no {entry.quant}; downloads would use {quant} instead")
    if result.download_gb <= 0:
        result.errors.append("the chosen file(s) report no size")
    elif entry.min_ram_gb < result.download_gb * MIN_HEADROOM:
        result.warnings.append(
            f"min_ram_gb={entry.min_ram_gb} is too low for a {result.download_gb} GB download ({quant}); "
            f"suggest {result.suggested_min_ram_gb}"
        )
    return result


def fetch_tree(client: httpx.Client, repo: str) -> list[dict[str, Any]]:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = client.get(f"{HF_BASE}/api/models/{repo}/tree/main", params={"recursive": "true"}, headers=headers)
    if resp.status_code == 404:
        raise LlamaCppError(f"repository {repo} was not found on Hugging Face")
    if resp.status_code in (401, 403):
        raise LlamaCppError(f"{repo} needs a Hugging Face login (set HF_TOKEN)")
    resp.raise_for_status()
    return resp.json()


def check_all(client: httpx.Client | None = None) -> list[Assessment]:
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    out: list[Assessment] = []
    try:
        for entry in MODEL_CATALOG:
            try:
                out.append(assess(entry, fetch_tree(client, entry.hf_repo)))
            except (LlamaCppError, httpx.HTTPError) as exc:
                failed = Assessment(entry)
                failed.errors.append(str(exc) or type(exc).__name__)
                out.append(failed)
    finally:
        if own:
            client.close()
    return out


def main() -> int:
    results = check_all()
    for r in results:
        detail = "; ".join(r.errors + r.warnings) or f"{r.quant_used}, {r.download_gb} GB"
        print(f"{r.level.upper():7} {r.entry.id:16} {r.entry.hf_repo}: {detail}")
        if os.environ.get("GITHUB_ACTIONS"):
            if r.errors:
                print(f"::error title=catalog {r.entry.id}::{'; '.join(r.errors)}")
            elif r.warnings:
                print(f"::warning title=catalog {r.entry.id}::{'; '.join(r.warnings)}")
    return 1 if any(r.errors for r in results) or (os.environ.get("CATALOG_STRICT") and any(r.warnings for r in results)) else 0


if __name__ == "__main__":
    sys.exit(main())
