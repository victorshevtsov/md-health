"""Rich-based terminal reporting."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from rich.console import Console, Group, RenderableType
from rich.markup import escape
from rich.padding import Padding
from rich.table import Table

from md_health.parser import Link, LinkKind, Status

STATUS_STYLE = {
    Status.GOOD: "green",
    Status.BROKEN: "red",
    Status.UNKNOWN: "yellow",
    Status.UNSUPPORTED: "dim cyan",
}

KIND_LABELS = {
    LinkKind.LOCAL_LINK: "Local links",
    LinkKind.LOCAL_IMAGE: "Local images",
    LinkKind.REMOTE_LINK: "Remote links",
    LinkKind.REMOTE_IMAGE: "Remote images",
    LinkKind.UNSUPPORTED: "Unsupported scheme",
}


def make_console() -> Console:
    return Console()


def _summary_section(links: list[Link]) -> Table:
    counts = Counter(link.status for link in links)
    table = Table(title="md-health summary", box=None, show_header=False)
    table.add_column(justify="right", style="bold")
    table.add_column()
    table.add_row("Total links/images:", str(len(links)))
    for status in (Status.GOOD, Status.BROKEN, Status.UNKNOWN, Status.UNSUPPORTED):
        style = STATUS_STYLE[status]
        table.add_row(
            f"{status.value.capitalize()}:", f"[{style}]{counts.get(status, 0)}[/{style}]"
        )
    return table


def _breakdown_table(links: list[Link]) -> Table:
    table = Table(title="Breakdown by type", box=None)
    table.add_column("Type")
    table.add_column("Count", justify="right")
    kind_counts = Counter(link.kind for link in links)
    for kind, label in KIND_LABELS.items():
        table.add_row(label, str(kind_counts.get(kind, 0)))
    return table


def _skipped_dirs_section(console: Console, skipped: set[str]) -> None:
    if not skipped:
        console.print("[dim]No directories were skipped.[/dim]")
        return
    console.print("[bold]Skipped directories:[/bold] " + escape(", ".join(sorted(skipped))))


def _issue_block(link: Link, root: Path) -> RenderableType:
    """One non-good link, rendered as a compiler-style diagnostic block."""
    style = STATUS_STYLE[link.status]
    if link.resolved_path is not None:
        resolved = os.path.relpath(link.resolved_path, root)
    else:
        resolved = link.path_part or "-"
    location = f"{os.path.relpath(link.source_file, root)}:{link.line}"

    details = Table.grid(padding=(0, 1))
    details.add_column(style="dim")
    details.add_column(overflow="fold")
    details.add_row("Raw:", escape(link.raw))
    details.add_row("Resolved:", escape(resolved))
    details.add_row("Reason:", escape(link.reason or "-"))

    body = Group(
        f"[dim]{link.kind.value}[/dim]  [{style}]{link.status.value}[/{style}]",
        details,
    )
    return Group(
        f"[bold {style}]{escape(location)}[/bold {style}]",
        Padding(body, (0, 0, 0, 2)),
    )


def _issues_section(links: list[Link], root: Path) -> Table:
    table = Table(title="Issues found", box=None, show_header=False, padding=0)
    table.add_column(overflow="fold")

    non_good = [link for link in links if link.status != Status.GOOD]
    for i, link in enumerate(sorted(non_good, key=lambda x: (str(x.source_file), x.line))):
        if i:
            table.add_row("")
        table.add_row(_issue_block(link, root))
    return table


def report(
    console: Console,
    root: Path,
    md_files: list[Path],
    skipped_dirs: set[str],
    links: list[Link],
) -> None:
    if not md_files:
        console.print("[yellow]No markdown files found.[/yellow]")
        return

    console.print(_summary_section(links))
    console.print(_breakdown_table(links))
    _skipped_dirs_section(console, skipped_dirs)

    non_good = [link for link in links if link.status != Status.GOOD]
    if non_good:
        console.print(_issues_section(links, root))
    else:
        console.print("[green]No broken, unknown, or unsupported links found.[/green]")
