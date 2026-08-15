"""Rich-based terminal reporting."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
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


def _summary_panel(links: list[Link]) -> Panel:
    counts = Counter(link.status for link in links)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="bold")
    grid.add_column()
    grid.add_row("Total links/images:", str(len(links)))
    for status in (Status.GOOD, Status.BROKEN, Status.UNKNOWN, Status.UNSUPPORTED):
        style = STATUS_STYLE[status]
        grid.add_row(
            f"{status.value.capitalize()}:", f"[{style}]{counts.get(status, 0)}[/{style}]"
        )
    return Panel(grid, title="md-health summary", border_style="cyan")


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


def _findings_table(links: list[Link], root: Path) -> Table:
    table = Table(title="Issues found")
    for col in ("File", "Line", "Type", "Raw", "Resolved target", "Status", "Reason"):
        table.add_column(col, overflow="fold")

    non_good = [link for link in links if link.status != Status.GOOD]
    for link in sorted(non_good, key=lambda x: (str(x.source_file), x.line)):
        style = STATUS_STYLE[link.status]
        if link.resolved_path is not None:
            resolved = os.path.relpath(link.resolved_path, root)
        else:
            resolved = link.path_part or "-"
        table.add_row(
            escape(os.path.relpath(link.source_file, root)),
            str(link.line),
            link.kind.value,
            escape(link.raw),
            escape(resolved),
            f"[{style}]{link.status.value}[/{style}]",
            escape(link.reason or "-"),
        )
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

    console.print(_summary_panel(links))
    console.print(_breakdown_table(links))
    _skipped_dirs_section(console, skipped_dirs)

    non_good = [link for link in links if link.status != Status.GOOD]
    if non_good:
        console.print(_findings_table(links, root))
    else:
        console.print("[green]No broken, unknown, or unsupported links found.[/green]")
