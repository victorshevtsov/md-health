"""Validation of local file/anchor targets and remote HTTP(S) URLs."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

import httpx

from md_health.parser import (
    MARKDOWN_EXTS,
    Link,
    LinkKind,
    ParsedFile,
    Status,
    parse_file,
)

_SLUG_STRIP_RE = re.compile(r"[^\w\- ]", re.UNICODE)

REMOTE_TIMEOUT_SECONDS = 1.0
REMOTE_MAX_REDIRECTS = 3
REMOTE_CONCURRENCY = 3


def github_slug(text: str, seen: dict[str, int]) -> str:
    slug = text.strip().lower()
    slug = _SLUG_STRIP_RE.sub("", slug)
    slug = slug.replace(" ", "-")
    if slug in seen:
        seen[slug] += 1
        return f"{slug}-{seen[slug]}"
    seen[slug] = 0
    return slug


def build_anchor_set(headings: list[str], raw_anchors: list[str]) -> set[str]:
    seen: dict[str, int] = {}
    return {github_slug(h, seen) for h in headings} | set(raw_anchors)


def check_local_link(
    link: Link,
    root: Path,
    file_index: dict[Path, ParsedFile],
    anchor_cache: dict[Path, set[str]],
) -> None:
    if link.status != Status.PENDING:
        return
    if link.kind not in (LinkKind.LOCAL_LINK, LinkKind.LOCAL_IMAGE):
        return

    if link.path_part == "":
        resolved = link.source_file
    else:
        decoded = unquote(link.path_part)
        base = root if decoded.startswith("/") else link.source_file.parent
        resolved = (base / decoded.lstrip("/")).resolve()
    link.resolved_path = resolved

    if not resolved.exists():
        link.status, link.reason = Status.BROKEN, "file not found"
        return

    if link.fragment:
        if resolved.suffix.lower() not in MARKDOWN_EXTS:
            link.status = Status.GOOD
            return
        anchors = anchor_cache.get(resolved)
        if anchors is None:
            pf = file_index.get(resolved) or parse_file(resolved)
            anchors = build_anchor_set(pf.headings, pf.raw_anchors)
            anchor_cache[resolved] = anchors
        if link.fragment not in anchors:
            link.status = Status.BROKEN
            link.reason = f"anchor '#{link.fragment}' not found in {resolved.name}"
            return
        link.status = Status.GOOD
        return

    link.status = Status.GOOD


async def _check_one_remote(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    link: Link,
    on_start: Callable[[Link], None] | None,
) -> None:
    async with sem:
        if on_start is not None:
            on_start(link)
        url = link.path_part
        try:
            resp = await client.head(url)
            if resp.status_code == 405:
                resp = await client.get(url)
        except httpx.TooManyRedirects:
            link.status, link.reason = Status.BROKEN, "too many redirects"
            return
        except httpx.TimeoutException:
            link.status, link.reason = Status.BROKEN, "timeout"
            return
        except httpx.TransportError as e:
            link.status, link.reason = Status.BROKEN, f"connection error: {e}"
            return
        except httpx.HTTPError as e:
            link.status, link.reason = Status.BROKEN, f"request error: {e}"
            return

        code = resp.status_code
        if code == 403:
            link.status, link.reason = Status.UNKNOWN, "HTTP 403 (unknown)"
        elif 200 <= code < 400:
            link.status, link.reason = Status.GOOD, None
        else:
            link.status, link.reason = Status.BROKEN, f"HTTP {code}"


async def check_remote_links(
    links: list[Link], on_start: Callable[[Link], None] | None = None
) -> None:
    remote = [
        link for link in links if link.kind in (LinkKind.REMOTE_LINK, LinkKind.REMOTE_IMAGE)
    ]
    if not remote:
        return

    sem = asyncio.Semaphore(REMOTE_CONCURRENCY)
    limits = httpx.Limits(
        max_connections=REMOTE_CONCURRENCY, max_keepalive_connections=REMOTE_CONCURRENCY
    )
    timeout = httpx.Timeout(REMOTE_TIMEOUT_SECONDS)
    headers = {"User-Agent": "md-health/0.1 (+link checker)"}

    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=REMOTE_MAX_REDIRECTS,
        timeout=timeout,
        limits=limits,
        headers=headers,
        verify=True,
    ) as client:
        await asyncio.gather(
            *(_check_one_remote(client, sem, link, on_start) for link in remote)
        )
