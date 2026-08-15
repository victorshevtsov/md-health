"""Command-line entry point: directory walk, orchestration, exit code."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from md_health import checker, parser, reporter
from md_health.parser import Link, MARKDOWN_EXTS, ParsedFile

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="md-health",
        description="Check markdown files for broken links, images, and anchors.",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    return p.parse_args(argv)


def discover_markdown_files(root: Path) -> tuple[list[Path], set[str]]:
    md_files: list[Path] = []
    skipped: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        keep = []
        for d in dirnames:
            if d in IGNORED_DIRS:
                skipped.add(d)
            else:
                keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            if Path(fn).suffix.lower() in MARKDOWN_EXTS:
                md_files.append((Path(dirpath) / fn).resolve())
    return sorted(md_files), skipped


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.path).resolve()
    console = reporter.make_console()

    md_files, skipped_dirs = discover_markdown_files(root)

    file_index: dict[Path, ParsedFile] = {}
    for f in md_files:
        file_index[f] = parser.parse_file(f)

    all_links: list[Link] = [link for pf in file_index.values() for link in pf.links]

    anchor_cache: dict[Path, set[str]] = {}
    with reporter.link_progress(console, len(all_links)) as on_start:
        for link in all_links:
            if link.kind not in (parser.LinkKind.REMOTE_LINK, parser.LinkKind.REMOTE_IMAGE):
                on_start(link)
            checker.check_local_link(link, root, file_index, anchor_cache)

        asyncio.run(checker.check_remote_links(all_links, on_start=on_start))

    reporter.report(
        console,
        root=root,
        md_files=md_files,
        skipped_dirs=skipped_dirs,
        links=all_links,
    )
    return 0


def cli_main() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli_main()
