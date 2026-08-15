Add a live progress indicator while links are being checked, plus three report tweaks — a scanned-file count, a retitled summary section naming the scanned path, and the issue reason folded onto the type/status line — in the repo at `/home/svn/study/larchenko/md-health`.

**Background**: `md-health` is a Python CLI that recursively scans a directory tree of Markdown files, extracts every link/image, validates them (local file + anchor existence, remote HTTP(S) reachability), and prints a Rich-based report at the end. On a large tree the tool currently prints *nothing at all* until every check is finished — remote checks in particular run with a 1 second timeout and concurrency 3, so a doc tree with many remote links can sit silent for a long time. There is also no indication of how many Markdown files were actually scanned.

**Current control flow** — `md_health/cli.py::main`:

```python
md_files, skipped_dirs = discover_markdown_files(root)          # sorted list[Path], set[str]

file_index: dict[Path, ParsedFile] = {}
for f in md_files:
    file_index[f] = parser.parse_file(f)

all_links: list[Link] = [link for pf in file_index.values() for link in pf.links]

anchor_cache: dict[Path, set[str]] = {}
for link in all_links:
    checker.check_local_link(link, root, file_index, anchor_cache)   # no-ops unless kind is LOCAL_LINK/LOCAL_IMAGE

asyncio.run(checker.check_remote_links(all_links))

reporter.report(console, root=root, md_files=md_files, skipped_dirs=skipped_dirs, links=all_links)
return 0
```

**Other relevant code**:

- `md_health/checker.py::check_remote_links(links: list[Link]) -> None` filters `all_links` down to `LinkKind.REMOTE_LINK`/`REMOTE_IMAGE`, returns early if there are none, then builds one `httpx.AsyncClient` plus an `asyncio.Semaphore(REMOTE_CONCURRENCY)` and `await asyncio.gather(*(_check_one_remote(client, sem, link) for link in remote))`. `_check_one_remote(client, sem, link)` does `async with sem:` and then issues the `HEAD`/`GET`.
- `md_health/parser.py::Link` has `source_file: Path`, `line: int`, `kind: LinkKind`, `raw: str` (the full original markup, e.g. `[Example #5](examples/example-005.md)`), `path_part: str`, `fragment`, `resolved_path`, `status: Status`, `reason`.
- `md_health/reporter.py` owns all console work: `make_console() -> Console`, the shared `_titled_table` / `_section` helpers, `_summary_section(links)`, `_breakdown_section(links)`, `_skipped_dirs_section(console, skipped)`, `_issues_section(links, root)`, and `report(console, root, md_files, skipped_dirs, links)`. `report()` already receives `md_files` but only uses it for the `if not md_files:` early return.

Current summary section as rendered today:

```
 md-health summary
 Total links/images:  6
               Good:  1
             Broken:  4
            Unknown:  0
        Unsupported:  1
```

**Required changes**:

### 1. Live progress line during link checking

While links are being checked, print a single line that is **updated in place** (not appended, one line per link) showing the link currently being checked, its 1-based index, and the total number of links:

```
Checking [5/125] [Example #5](examples/example-005.md)
```

Specifics:

- **Total** is `len(all_links)` — the same number the report's `Total links/images:` row shows. Links with unsupported schemes are included in the total and tick past like any other; do not carve out a separate "checkable links" total.
- **Index** is 1-based and identifies the link *currently being worked on*, so it is incremented when a link's check *starts*, not when it finishes. It must reach the total exactly once, with no double counting: the local pass and the remote pass share one counter.
- **The displayed link** is `link.raw`. Collapse whitespace first (`" ".join(link.raw.split())`) so a link whose markup spans a line break can't turn the one-line indicator into two lines.
- **Escaping**: `link.raw` routinely contains `[...]`, and the counter itself is written with square brackets. Run the whole composed line through `rich.markup.escape` (or build it as a `rich.text.Text`, which is never markup-parsed) — a raw link containing something like `[bold]` must render literally and must not crash.
- **Truncation**: the line must never wrap. Constrain it to the console width with ellipsis overflow (e.g. a `TextColumn` whose `table_column=Column(no_wrap=True, overflow="ellipsis")`, or `Text.truncate(...)`). Verify at a narrow width, not just at your default terminal size.
- **Transient**: when checking finishes, the progress line must be erased, leaving no residue above the report. The report's first line (` md-health summary`) must land at the start of a clean line.
- **Non-TTY**: when the console is not a terminal (piped/redirected output), the indicator must be suppressed entirely — piped output must be byte-for-byte the report only. Gate on `console.is_terminal` (e.g. `Progress(..., disable=not console.is_terminal)`); do not rely on Rich's default behavior, which still emits the line once. Colour is a separate concern: with `NO_COLOR` set on a real TTY the indicator should still appear, just uncoloured.
- **Zero links**: if `all_links` is empty, don't start a progress display at all.

**Suggested implementation** (take a cleaner arrangement if you find one; the requirement is the behavior above, not this decomposition):

- Put the display in `md_health/reporter.py` — it owns everything console-related. A context manager reads well, e.g.

  ```python
  @contextmanager
  def link_progress(console: Console, total: int) -> Iterator[Callable[[Link], None]]:
      """Yields a callback to invoke as each link's check begins."""
  ```

  implemented with `rich.progress.Progress(TextColumn("{task.description}"), console=console, transient=True, disable=not console.is_terminal)` and a single task of `total=total`, where the yielded callback bumps a counter and calls `progress.update(task_id, completed=n, description=<escaped line>)`. A `rich.live.Live` wrapping a `Text` is an equally acceptable vehicle — there is no bar, percentage, or ETA to render, only the one line. When the callback is a no-op (`total == 0`, or disabled), keep the yielded callable valid so callers need no branching.
- Wire it in `md_health/cli.py::main` around both check phases, so one counter spans them:
  - Local pass: iterate `all_links` as today, but invoke the callback only for links whose kind is *not* remote (remote links are counted by the remote pass — otherwise they'd be counted twice). `check_local_link` already no-ops for the rest.
  - Remote pass: give `checker.check_remote_links` a new optional keyword parameter, e.g. `on_start: Callable[[Link], None] | None = None`, defaulting to `None` so the existing signature keeps working. Pass it through to `_check_one_remote` and invoke it *inside* `async with sem:` immediately before the `HEAD` request — that is the moment the link is genuinely in flight. Everything runs on one event loop thread, so the counter needs no locking.
  - Consequence worth knowing (and fine): with concurrency 3, up to three remote links are in flight at once, so the line shows the most recently started one and remote links are not displayed in file order. Local links are displayed in `all_links` order.
- Keep `md_health/checker.py` free of Rich imports — it takes a plain callable, nothing more.
- The file-parsing phase (`parser.parse_file` per file) is out of scope; only link checking gets a progress line.

### 2. Files scanned in the summary

Add a `Files scanned:` row to the summary section as its **first** row, above `Total links/images:`, with the value `len(md_files)` — plain/uncoloured, like the total (the per-status colours stay exclusive to the status rows). `report()` already has `md_files`; give `_summary_section` the count (e.g. `_summary_section(links: list[Link], file_count: int)`) rather than reaching for a global. Target:

```
 Markdown Health summary for /home/svn/study/larchenko/md-health
      Files scanned:  12
 Total links/images:  6
               Good:  1
             Broken:  4
            Unknown:  0
        Unsupported:  1
```

(Rich sizes the label column, so exact padding will shift — the point is that the new row is part of the same section, in the same shape.) Do not touch `_breakdown_section`, `_skipped_dirs_section`, `_issues_section`, the section helpers, or the blank-line spacing between sections.

### 3. Retitle the summary section with the scanned path

Replace the `md-health summary` section title with `Markdown Health summary for <path>`, where `<path>` is the absolute directory that was scanned — `report()`'s `root` argument, which `cli.py::main` has already run through `Path(args.path).resolve()`, so it is absolute and symlink-free with no extra work. Print it as `str(root)` (a plain absolute path, not `repr`, not relative, not `~`-abbreviated); on this machine, running `md-health` with no argument from the repo yields `Markdown Health summary for /home/svn/study/larchenko/md-health`.

- Pass `root` into `_summary_section` (e.g. `_summary_section(links: list[Link], file_count: int, root: Path)`) — `report()` already receives it. Keep using the shared `_section(title)` helper so the title keeps its left-aligned italic-dim treatment and stays visually consistent with `Breakdown by type` and `Issues found`; only the title string changes.
- Escape the path with `rich.markup.escape` before it reaches the title — a directory name containing `[` would otherwise be swallowed as markup.
- The title can now be much wider than the two-column body, which widens the table Rich renders. Look at the result; if a long path makes the section look broken (e.g. the title wrapping mid-path), fix it sensibly rather than leaving it — truncating the *middle* of an over-wide path is acceptable, dropping the path is not.
- Only the summary title changes. `Breakdown by type` and `Issues found` keep their titles.

### 4. Fold the issue reason into the type/status line

`_issue_block` currently renders each non-good link as:

```
doc.md:3
  local-link  broken
  Raw:       [a](./missing.md)
  Resolved:  missing.md
  Reason:    file not found
```

Move the reason onto the type/status line, appended after a ` - ` separator, and drop the `Reason:` row from the detail grid:

```
doc.md:3
  local-link  broken - file not found
  Raw:       [a](./missing.md)
  Resolved:  missing.md
```

- Keep the existing styling of the first two elements exactly: `link.kind.value` dim, `link.status.value` in `STATUS_STYLE[link.status]`, two spaces between them. Render the reason itself in the default style (a dim separator is fine); do not colour it with the status style — the status word stays the coloured element.
- `link.reason` is `str | None` and is legitimately `None` for some links. When it is `None`, omit the separator and the reason entirely — the line is just `local-link  broken`. Do not emit a dangling `- ` or the old `-` placeholder.
- Keep `rich.markup.escape` on the reason; reasons are built from file contents and URLs (e.g. `anchor '#x' not found in doc.md`, `connection error: ...`) and can contain brackets.
- The detail grid keeps `Raw:` and `Resolved:` in that order, with the same dim labels, same alignment, and same `overflow="fold"` on the value column. Everything else about the issue block — the `file:line` header line, its bold+status colour, the two-space indent, the blank line between issues, the sort order — is unchanged.
- No information is lost: every issue still reports file, line, kind, status, raw markup, resolved target, and reason.

### 5. Docs

- Update `README.md`: mention the live progress line under Usage (one line, updated in place, showing the link being checked with its position and the total) and that it is suppressed when output is not a TTY. Also make sure nothing in README contradicts the new summary row, the new summary title, or the reshaped issue block.
- Check `spec/usage.md` — at the time of writing it contains no sample output, only a cost/duration block; confirm rather than assume.
- Leave `spec/spec.md` alone unless something in it becomes factually wrong.

**Verification** (the repo has an editable-install `.venv` from a prior session — reuse it, or create one with `python3 -m venv .venv && .venv/bin/pip install -e .`; the system Python is externally-managed so a venv is required):

Build scratch fixtures **outside the repo** (e.g. under `/home/svn/.claude/jobs/*/tmp`):

1. **A big local fixture** — script the generation of ~50 `.md` files with a few links each (a mix of good targets, missing files, and missing anchors), so the counter visibly runs. Include at least one link whose text contains square brackets (e.g. `[a [nested] label](./x.md)`) and one containing a Rich-looking tag (e.g. `[see [bold] here](./x.md)`) to confirm escaping.
2. **A slow-remote fixture** — a `.md` file with ~12 links to an unroutable host or invalid TLD (e.g. `http://10.255.255.1/a`, `https://nonexistent.invalid/b`). With a 1s timeout and concurrency 3 the remote phase takes several seconds, which is the only way to actually watch the remote half of the counter move. Mix in local links so both phases are exercised in one run.

Then:

- Run `.venv/bin/md-health <fixture>` in a real terminal and **watch the output** — the exit code is always 0 and proves nothing. Confirm: one line, rewritten in place (no scrollback of hundreds of `Checking ...` lines); the index starts at 1, never exceeds the total, ends at the total; the total equals the `Total links/images:` value in the report that follows.
- Confirm the progress line is gone once the report prints, with no leftover text or stray blank line above the summary title.
- Run with output redirected (`.venv/bin/md-health <fixture> > out.txt 2>&1`) and inspect `out.txt`: it must contain no `Checking` text and no ANSI cursor-movement escapes, and apart from the four changes in this request must read exactly as it did before.
- Re-run at a narrow width (`COLUMNS=40 .venv/bin/md-health <fixture>`) and confirm the progress line truncates instead of wrapping or corrupting the display, and that the long absolute path in the summary title still leaves the section legible.
- Confirm the `Files scanned:` count matches reality: compare against `find <fixture> -name '*.md' | wc -l` (mind the ignored-directory list — add a `node_modules/` with a `.md` inside to confirm skipped directories are excluded from the count, since `discover_markdown_files` prunes them).
- Confirm the summary title shows the **absolute** scanned path in all invocation forms: `md-health` with no argument, `md-health .`, `md-health ./relative/sub`, and a path containing `..`. All must print a fully-resolved absolute path, never the literal argument. Test one directory whose name contains `[`brackets`]` to confirm escaping.
- Read the issue blocks: every non-good link must show `<kind>  <status> - <reason>` on one line with no `Reason:` row below, and `Raw:`/`Resolved:` still aligned. Cover a link whose `reason` is `None` and confirm the line ends cleanly after the status with no trailing separator (grep the codebase for where `reason` stays unset if you're unsure which case produces it, and construct that case).
- Run `.venv/bin/md-health .` against the repo itself and sanity-check the progress behavior, the new row, the title, and the issue blocks.
- Edge cases: a directory whose Markdown has zero links (progress must not appear or crash; report still renders), and a directory with no Markdown files at all (still just `No markdown files found.`).
- Confirm the all-good empty state is unchanged, and that the breakdown, skipped-directories, and issues section titles plus the blank-line spacing between sections are all untouched.
