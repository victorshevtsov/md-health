"""Extraction of links and images from Markdown files.

Uses markdown-it-py to identify prose (inline) regions of a document so that
fenced/indented code blocks are structurally excluded, and to resolve
reference-style link/image definitions. A regex is then run over the raw
source of each prose region to recover the exact line number and raw markup
of each link/image, since markdown-it-py's inline child tokens do not carry
per-child source positions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

_MD = MarkdownIt("commonmark")

MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd"}

_UNSUPPORTED_SCHEMES = {"mailto", "tel", "ftp", "file"}

_LINK_RE = re.compile(
    r'(?P<img>!)?\[(?P<text>[^\[\]]*)\]'
    r'(?:'
    r'\((?P<dest>(?:<[^<>\n]*>|[^()\s]*)(?:\s+"[^"]*"|\s+\'[^\']*\')?)\)'
    r'|'
    r'\[(?P<ref>[^\[\]]*)\]'
    r')'
)
_CODE_SPAN_RE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.DOTALL)
_HTML_ANCHOR_ATTR_RE = re.compile(
    r'<[a-zA-Z][\w-]*\b[^>]*?\b(?:id|name)\s*=\s*(?:"([^"]+)"|\'([^\']+)\')',
)


class LinkKind(str, Enum):
    LOCAL_LINK = "local-link"
    LOCAL_IMAGE = "local-image"
    REMOTE_LINK = "remote-link"
    REMOTE_IMAGE = "remote-image"
    UNSUPPORTED = "unsupported"


class Status(str, Enum):
    PENDING = "pending"
    GOOD = "good"
    BROKEN = "broken"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


@dataclass
class Link:
    source_file: Path
    line: int
    raw: str
    text: str
    target: str
    kind: LinkKind
    path_part: str
    fragment: str | None
    is_orphan_reference: bool = False
    resolved_path: Path | None = None
    status: Status = Status.PENDING
    reason: str | None = None


@dataclass
class ParsedFile:
    path: Path
    links: list[Link] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    raw_anchors: list[str] = field(default_factory=list)
    read_error: str | None = None


def _mask_code_spans(block_text: str) -> str:
    return _CODE_SPAN_RE.sub(lambda m: m.group(0)[0] * len(m.group(0)), block_text)


def _strip_title(dest: str) -> str:
    dest = dest.strip()
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1]
    m = re.match(r"^(\S*)(?:\s+(?:\"[^\"]*\"|'[^']*'))?$", dest)
    return m.group(1) if m else dest


def _heading_plain_text(tok: Token) -> str:
    parts: list[str] = []
    for c in tok.children or []:
        if c.type in ("text", "code_inline"):
            parts.append(c.content)
        elif c.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif c.type == "image":
            parts.append(c.content or c.attrs.get("alt", "") or "")
    return "".join(parts)


def _classify(target: str) -> tuple[str, str, str | None]:
    """Returns (kind_base, path_part, fragment)."""
    parts = urlsplit(target)
    fragment = unquote(parts.fragment) if parts.fragment else None
    scheme = parts.scheme.lower()
    if scheme in ("http", "https"):
        path_part = target.split("#", 1)[0]
        return "remote", path_part, fragment
    if scheme:
        return "unsupported", target.split("#", 1)[0], fragment
    return "local", parts.path, fragment


def _make_link(
    source_file: Path,
    line: int,
    raw: str,
    text: str,
    target: str,
    is_img: bool,
) -> Link:
    kind_base, path_part, fragment = _classify(target)
    if kind_base == "remote":
        kind = LinkKind.REMOTE_IMAGE if is_img else LinkKind.REMOTE_LINK
    elif kind_base == "unsupported":
        kind = LinkKind.UNSUPPORTED
    else:
        kind = LinkKind.LOCAL_IMAGE if is_img else LinkKind.LOCAL_LINK

    link = Link(
        source_file=source_file,
        line=line,
        raw=raw,
        text=text,
        target=target,
        kind=kind,
        path_part=path_part,
        fragment=fragment,
    )
    if kind == LinkKind.UNSUPPORTED:
        scheme = urlsplit(target).scheme or "unknown"
        link.status = Status.UNSUPPORTED
        link.reason = f"unsupported scheme ({scheme}:)"
    return link


def _make_dangling_reference_link(
    source_file: Path, line: int, raw: str, text: str, is_img: bool
) -> Link:
    link = Link(
        source_file=source_file,
        line=line,
        raw=raw,
        text=text,
        target="",
        kind=LinkKind.LOCAL_IMAGE if is_img else LinkKind.LOCAL_LINK,
        path_part="",
        fragment=None,
    )
    link.status = Status.BROKEN
    link.reason = "reference not found"
    return link


def parse_file(path: Path) -> ParsedFile:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ParsedFile(path=path, read_error=str(e))

    lines = text.splitlines()
    env: dict = {}
    tokens = _MD.parse(text, env)

    pf = ParsedFile(path=path)
    used_labels: set[str] = set()

    for i, tok in enumerate(tokens):
        if tok.type == "html_block":
            for m in _HTML_ANCHOR_ATTR_RE.finditer(tok.content):
                pf.raw_anchors.append(m.group(1) or m.group(2))
            continue

        if tok.type != "inline" or tok.map is None:
            continue

        start_line, end_line = tok.map
        block_text = "\n".join(lines[start_line:end_line])
        masked = _mask_code_spans(block_text)

        for m in _HTML_ANCHOR_ATTR_RE.finditer(masked):
            pf.raw_anchors.append(m.group(1) or m.group(2))

        prev = tokens[i - 1] if i > 0 else None
        if prev is not None and prev.type == "heading_open":
            pf.headings.append(_heading_plain_text(tok))
            continue

        for m in _LINK_RE.finditer(masked):
            line_offset = masked.count("\n", 0, m.start())
            line_no = start_line + line_offset + 1
            is_img = m.group("img") is not None
            link_text = m.group("text")
            raw = m.group(0)

            if m.group("dest") is not None:
                target = _strip_title(m.group("dest"))
                pf.links.append(
                    _make_link(path, line_no, raw, link_text, target, is_img)
                )
            else:
                label = m.group("ref") or link_text
                norm = " ".join(label.split()).upper()
                ref = env.get("references", {}).get(norm)
                if ref is None:
                    pf.links.append(
                        _make_dangling_reference_link(
                            path, line_no, raw, link_text, is_img
                        )
                    )
                    continue
                used_labels.add(norm)
                pf.links.append(
                    _make_link(path, line_no, raw, link_text, ref["href"], is_img)
                )

    for label, ref in env.get("references", {}).items():
        if label in used_labels:
            continue
        def_line_idx = ref["map"][0] if ref.get("map") else 0
        def_line = def_line_idx + 1
        raw = (
            lines[def_line_idx]
            if 0 <= def_line_idx < len(lines)
            else f'[{label}]: {ref["href"]}'
        )
        link = _make_link(path, def_line, raw, label, ref["href"], is_img=False)
        link.is_orphan_reference = True
        pf.links.append(link)

    return pf
