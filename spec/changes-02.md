Change the terminal output format of `md-health`, in the repo at `/home/svn/study/larchenko/md-health`.

**Background**: `md-health` is a Python CLI that scans Markdown files for broken links/images/anchors and prints a Rich-based report. All rendering lives in `md_health/reporter.py`; `md_health/cli.py::main` calls `reporter.report(console, root=..., md_files=..., skipped_dirs=..., links=...)` once at the end.

`report()` currently prints four things in order:
1. `_summary_panel(links)` — a `Table.grid` of totals (total count + one row per `Status`: good/broken/unknown/unsupported, colored via `STATUS_STYLE`), wrapped in `rich.panel.Panel(grid, title="md-health summary", border_style="cyan")`.
2. `_breakdown_table(links)` — `Table(title="Breakdown by type", box=None)` with `Type` / `Count` columns, one row per `LinkKind` using `KIND_LABELS`.
3. `_skipped_dirs_section(console, skipped)` — one line.
4. `_findings_table(links, root)` — `Table(title="Issues found")` with boxed columns `File`, `Line`, `Type`, `Raw`, `Resolved target`, `Status`, `Reason`, one row per link whose `status != Status.GOOD`, sorted by `(str(source_file), line)`. If there are no such links it prints a green "No broken, unknown, or unsupported links found." line instead.

Relevant data: `Link` (in `md_health/parser.py`) has `source_file: Path`, `line: int`, `kind: LinkKind`, `raw: str`, `path_part: str`, `resolved_path: Path | None`, `status: Status`, `reason: str | None`. The existing findings table computes the resolved target as `os.path.relpath(link.resolved_path, root)` when `resolved_path is not None`, else `link.path_part or "-"`, and file paths as `os.path.relpath(link.source_file, root)`.

**Required changes** — both in `md_health/reporter.py` only; do not change the data model, checker, or CLI:

1. **Drop the summary panel frame.** Remove the `Panel` wrapper (and the now-unused `rich.panel` import) from `_summary_panel`. Instead print a section header followed by a line break and then the summary rows, styled to match how the "Breakdown by type" section already renders its title. Inspect the actual rendered output of the breakdown section first and match it — do not guess. Rich's default `Table.title` style is centered italic dim over the table width, so the cleanest way to get a genuinely identical look is to render the summary as a `Table(title="md-health summary", box=None)` with the same right-aligned-label / value column shape it has now, rather than hand-rolling a `console.print("[bold]...[/bold]")` header that would look different. Keep the existing per-status colors from `STATUS_STYLE`. Rename the function if `_summary_panel` no longer describes it (e.g. `_summary_section`).

2. **Replace the "Issues found" table with a per-issue list.** Remove `_findings_table` and render each non-good link as a compiler-diagnostic-style block. Same set of links, same sort order (`(str(source_file), line)`) as today. Target layout per issue:

   ```
   docs/guide.md:42
     local-link  broken
     Raw:       [setup](./setup.md#install)
     Resolved:  docs/setup.md
     Reason:    anchor '#install' not found in target file
   ```

   Specifics:
   - First line is `<path>:<line>` with the path relative to `root` (as today), in the compiler `file:line` form so terminals can make it clickable. Give it a style that makes it scannable (e.g. bold, or bold plus the status color).
   - Second line carries `link.kind.value` and `link.status.value` together, with the status colored via `STATUS_STYLE[link.status]` exactly as the table did.
   - Then one line each for `Raw`, `Resolved target`, and `Reason`, in that order, with the labels aligned so the values line up. Use the same fallbacks as the current table: resolved target is `os.path.relpath(link.resolved_path, root)` or `link.path_part or "-"`; reason is `link.reason or "-"`.
   - Keep the detail lines indented under the `file:line` header, and separate consecutive issues with a blank line so the list stays readable.
   - Keep using `rich.markup.escape` on every value that comes from file contents (`raw`, resolved target, reason, paths) — link text routinely contains `[...]`, which Rich would otherwise eat as markup.
   - Precede the list with an "Issues found" header rendered the same way as the other section headers from change 1, so all three sections are visually consistent.
   - Preserve the existing empty-state behavior: when every link is `Status.GOOD`, still print the green "No broken, unknown, or unsupported links found." line and no header/list.
   - `Table` may still be a convenient implementation vehicle (e.g. a `Table.grid` per issue for label alignment) — what must go is the single bordered multi-column table, not the use of Rich primitives.

   If you find a cleaner arrangement of these same five pieces of information (file:line, type+status, raw, resolved target, reason) while implementing, use it — the layout above is a concrete target, not a spec to satisfy literally. Do not add, drop, or reorder the information itself.

3. Check `README.md` and `spec/usage.md` for sample output or descriptions of the report format, and update anything that no longer matches. `spec/spec.md` line 49-52 describes the summary requirements generically ("Colored summary showing..." / "Breakdown by type") — leave `spec/spec.md` alone unless something there is now factually wrong.

**Verification** (the repo has an editable-install `.venv` from a prior session — reuse it, or create one with `python3 -m venv .venv && .venv/bin/pip install -e .`; the system Python is externally-managed so a venv is required):

- Build a scratch fixture directory under `/home/svn/.claude/jobs/*/tmp` or similar (not inside the repo) with a couple of `.md` files that produce a mix of statuses: a broken local link, a broken anchor, an unsupported scheme (e.g. `mailto:`), a good local link, and at least one link whose text contains square brackets or other Rich-markup-like characters, to confirm escaping still works.
- Run `.venv/bin/md-health <fixture-dir>` and **look at the rendered output** — exit code is always 0 and proves nothing.
- Also run `.venv/bin/md-health .` against the repo itself, and run it with output piped to a file (`| cat` / redirect) to confirm the non-TTY plain-text fallback still reads sensibly and nothing relies on the panel border for structure.
- Confirm the all-good empty state by running against a directory whose Markdown has only valid links.
