Generalize the section layout of the `md-health` terminal report, in the repo at `/home/svn/study/larchenko/md-health`.

**Background**: `md-health` is a Python CLI that scans Markdown files for broken links/images/anchors and prints a Rich-based report. All rendering lives in `md_health/reporter.py`; `md_health/cli.py::main` calls `reporter.report(console, root=..., md_files=..., skipped_dirs=..., links=...)` once at the end. Nothing outside `reporter.py` needs to change.

`report()` currently prints, in order, with no blank lines between them:

1. `_summary_section(links)` — `Table(title="md-health summary", box=None, show_header=False)` with a right-aligned bold label column and a value column; one row for the total, then one row per `Status` (good/broken/unknown/unsupported) whose value is colored via `STATUS_STYLE`.
2. `_breakdown_table(links)` — `Table(title="Breakdown by type", box=None)` with visible `Type` / `Count` column headers, one row per `LinkKind` using `KIND_LABELS`.
3. `_skipped_dirs_section(console, skipped)` — a single line: either `[dim]No directories were skipped.[/dim]` or `[bold]Skipped directories:[/bold] a, b, c`.
4. `_issues_section(links, root)` — `Table(title="Issues found", box=None, show_header=False, padding=0)` wrapping one `_issue_block` per non-good link, blank row between blocks. When every link is `Status.GOOD` it prints `[green]No broken, unknown, or unsupported links found.[/green]` instead, with no header.

Current rendered output (real, captured from a fixture run — note the centered titles and the absence of blank lines between sections):

```
   md-health summary
 Total links/images:  2
               Good:  0
             Broken:  2
            Unknown:  0
        Unsupported:  0
     Breakdown by type
 Type                 Count
 Local links              2
 Local images             0
 Remote links             0
 Remote images            0
 Unsupported scheme       0
No directories were skipped.
                Issues found
t.md:3
  local-link  broken
  Raw:       [a](./missing.md)
  Resolved:  missing.md
  Reason:    file not found

t.md:5
  local-link  broken
  Raw:       [c](./t.md#nope)
  Resolved:  t.md
  Reason:    anchor '#nope' not found in t.md
```

The summary section's shape — a titled, borderless, header-less two-column table of right-aligned bold labels and left-aligned values — is the look we want everywhere. The goal of this change is to make that shape the shared, reusable section format rather than a one-off.

**Required changes** (all in `md_health/reporter.py`; do not change the data model, checker, or CLI):

1. **Extract a shared section builder.** Add a small helper — e.g. `_section(title: str) -> Table` — that returns the common section table: `box=None`, `show_header=False`, left-justified title, and the two-column label/value shape used by the summary today (`add_column(justify="right", style="bold")` + `add_column()`). Build the summary and the breakdown from it so they are guaranteed to render identically; the issues section shares the title treatment but has its own single-column body (see point 4). Prefer one helper that both label/value sections call over duplicating column setup.

2. **Left-align every section header.** Rich centers `Table.title` over the table width by default (see the captured output above). Pass `title_justify="left"` so all headers start at the same column. Keep Rich's default title style (italic dim) — only the justification changes. Watch out for the leading pad cell Rich inserts with `box=None`: a left-justified title may land one character left of the row labels. Render it and look at the result; if the header and the body are visibly off, align them (e.g. by adjusting `padding` or prefixing the title with a space) rather than leaving the mismatch.

3. **Reshape "Breakdown by type" to match the summary.** Drop the visible `Type` / `Count` column headers and render it through the same helper: right-aligned bold label with a trailing colon, then the count. Keep the `KIND_LABELS` text and the same row order, adding the colon the way the summary does (`"Local links:"`, `"Local images:"`, …). Counts stay plain/uncolored — the per-status colors belong to the summary only. Target:

   ```
   Breakdown by type
        Local links: 2
       Local images: 0
       Remote links: 0
      Remote images: 0
   Unsupported scheme: 0
   ```

   (Rich sizes the label column, so exact padding will differ — the point is that the two sections read as one format.) Rename `_breakdown_table` to `_breakdown_section` to match `_summary_section`.

4. **Give the issues section the same header treatment.** `_issues_section` keeps its current per-issue `_issue_block` body (file:line header, `kind` + colored `status`, then aligned `Raw` / `Resolved` / `Reason` lines) — do not restyle the issue blocks themselves. Only its title must pick up the shared left-aligned treatment, so all three headers line up.

5. **Blank line between sections.** Separate the four top-level sections (summary, breakdown, skipped directories, issues) with one blank line each — `console.line()` between `console.print(...)` calls is fine. No trailing blank line after the last section, and no leading blank line before the first. The all-good `No broken, unknown, or unsupported links found.` line takes the issues section's place and gets the same separation. The `_skipped_dirs_section` one-liner stays a one-liner (bold inline label, no italic-dim title) — it participates in the blank-line spacing but is deliberately not converted into a titled section.

Target overall shape:

```
md-health summary
 Total links/images: 2
                Good: 0
              Broken: 2
             Unknown: 0
         Unsupported: 0

Breakdown by type
         Local links: 2
        ...

No directories were skipped.

Issues found
t.md:3
  local-link  broken
  ...
```

If while implementing you find a cleaner way to express "these sections all share one format" (a single `_section` factory, a small list of `(title, rows)` pairs rendered by one loop, etc.), take it — the requirement is the shared, left-aligned, blank-line-separated look, not a particular function decomposition. Do not add, drop, or reorder any of the reported information.

6. Check `README.md` and `spec/usage.md` for sample output or descriptions of the report format and update anything that no longer matches (at the time of writing neither contains sample output — confirm rather than assume). `spec/spec.md` lines ~49-52 describe the output requirements generically ("Colored summary showing…" / "Breakdown by type"); leave `spec/spec.md` alone unless something there becomes factually wrong.

**Verification** (the repo has an editable-install `.venv` from a prior session — reuse it, or create one with `python3 -m venv .venv && .venv/bin/pip install -e .`; the system Python is externally-managed so a venv is required):

- Build a scratch fixture directory outside the repo (e.g. under `/home/svn/.claude/jobs/*/tmp`) with a couple of `.md` files producing a mix of statuses: a broken local link, a broken anchor, an unsupported scheme (`mailto:`), a good local link, and at least one link whose text contains square brackets, to confirm Rich-markup escaping still works.
- Run `.venv/bin/md-health <fixture-dir>` and **read the rendered output** — the exit code is always 0 and proves nothing. Compare the summary and breakdown sections side by side; if they don't look like the same component, the change isn't done.
- Run `.venv/bin/md-health .` against the repo itself.
- Run it with output piped/redirected to a file to confirm the non-TTY plain-text fallback still reads sensibly and the blank lines land in the right places.
- Confirm the all-good empty state (a directory whose Markdown has only valid links) still prints the green line, still prints no "Issues found" header, and is spaced correctly.
