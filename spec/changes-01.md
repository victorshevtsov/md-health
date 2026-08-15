Add support for explicit HTML named anchors to `md-health`'s local-anchor validation, in the repo at `/home/svn/study/larchenko/md-health`.

**Background**: `md-health` is a Python CLI that scans Markdown files for broken links/images. Local links with a `#fragment` are validated by checking the fragment against a set of anchors built from the target file's headings (`md_health/checker.py::build_anchor_set`, called from `check_local_link`), using GitHub-style heading slugification (`github_slug`). This only covers auto-generated heading anchors. It's missing explicit HTML anchors that GitHub and other CommonMark renderers also treat as valid fragment targets: `<a name="foo"></a>`, `<a id="foo"></a>`, and any element with an `id="foo"` attribute (e.g. `<h2 id="foo">`, `<div id="foo">`). Currently, `[text](#foo)` or `[text](file.md#foo)` pointing at one of these is incorrectly reported as `broken`.

**Key implementation files**:
- `md_health/parser.py` — `ParsedFile` dataclass (currently: `path`, `links`, `headings: list[str]`, `read_error`), `parse_file(path) -> ParsedFile`, which walks `MarkdownIt("commonmark").parse(text, env)`'s flat token list, and for each `inline` token (identified via `tok.type == "inline" and tok.map is not None`) either (a) if immediately preceded by a `heading_open` token, extracts plain heading text into `pf.headings`, or (b) otherwise takes the raw source slice for that token's line range, masks inline code spans (`_mask_code_spans`), and regex-scans it (`_LINK_RE`) for links/images.
- `md_health/checker.py` — `github_slug(text, seen) -> str` (GitHub-style slugification with `-1`/`-2` duplicate suffixing) and `build_anchor_set(headings: list[str]) -> set[str]`, called once per target file inside `check_local_link` (memoized via `anchor_cache: dict[Path, set[str]]`).

**Empirically confirmed token shapes** (verify yourself with `MarkdownIt("commonmark").parse(text, {})` before assuming, but this is what we found):
- `<a name="x"></a>` / `<a id="x"></a>`, whether inline within a paragraph's prose or alone on its own line, is *not* a CommonMark HTML-block starter tag (`<a>` isn't in the block-tag list) — it ends up inside an ordinary `inline` token's raw source text, i.e. the same `block_text`/`masked` string `parse_file` already computes for `_LINK_RE` scanning.
- Block-level tag names (the CommonMark HTML-block type-6 list: `address`, `article`, ..., `h1`-`h6`, `div`, `p`, `table`, etc.) become their own standalone `html_block` token with `tok.content` holding the raw HTML — these are never wrapped in a sibling `inline` token, so `parse_file`'s current `tok.type == "inline"` loop never visits them at all.
- A heading whose own inline content contains raw HTML (e.g. `## Some <a id="x"></a> Heading`) currently short-circuits via the `if prev.type == "heading_open": ... continue` branch before any regex scan runs — so anchor tags embedded directly inside heading text are currently missed by both the old and any naively-added new logic unless you restructure this branch.

**Required changes**:

1. In `md_health/parser.py`:
   - Add a new field to `ParsedFile`: `raw_anchors: list[str] = field(default_factory=list)` — literal (non-slugified) `id`/`name` attribute values found anywhere in the file.
   - Add a module-level regex, e.g.:
     ```python
     _HTML_ANCHOR_ATTR_RE = re.compile(
         r'<[a-zA-Z][\w-]*\b[^>]*?\b(?:id|name)\s*=\s*(?:"([^"]+)"|\'([^\']+)\')',
     )
     ```
     (two alternative capture groups for double- vs single-quoted values; take whichever group matched, e.g. `m.group(1) or m.group(2)`.)
   - Restructure the per-`inline`-token loop in `parse_file` so the raw block-text slice (`start_line, end_line = tok.map`; `block_text = "\n".join(lines[start_line:end_line])`; `masked = _mask_code_spans(block_text)`) is computed *once per inline token regardless of whether it's a heading*, and run `_HTML_ANCHOR_ATTR_RE.finditer(masked)` against it unconditionally (both for heading-preceded and regular inline tokens), appending captured values to `pf.raw_anchors`, before the existing heading-vs-non-heading branch decides whether to also run `_LINK_RE`.
   - Add a second pass (separate loop, or folded into the same `for i, tok in enumerate(tokens)` loop with an `elif tok.type == "html_block":` branch) that runs `_HTML_ANCHOR_ATTR_RE.finditer(tok.content)` for every `html_block` token and appends captured values to `pf.raw_anchors`.
   - Do **not** run captured `id`/`name` values through `github_slug` or any normalization — HTML `id` fragment matching is case-sensitive and exact in browsers/GitHub, unlike auto-generated heading slugs. Store them verbatim.

2. In `md_health/checker.py`:
   - Change `build_anchor_set(headings: list[str]) -> set[str]` to `build_anchor_set(headings: list[str], raw_anchors: list[str]) -> set[str]`, returning the union: `{github_slug(h, seen) for h in headings} | set(raw_anchors)`.
   - Update the one call site inside `check_local_link` (currently `anchors = build_anchor_set(pf.headings)`) to `anchors = build_anchor_set(pf.headings, pf.raw_anchors)`.

3. Update `README.md`'s anchor-validation bullet to mention that explicit HTML anchors (`<a name>`/`<a id>`, or any element's `id="..."` attribute) are also recognized as valid fragment targets, alongside auto-generated heading slugs.

**Verification** (repo already has an editable-install `.venv` from a prior session — reuse it, or create one: `python3 -m venv .venv && .venv/bin/pip install -e .`; the system Python is externally-managed so a venv is required):

Build a scratch fixture `.md` file covering all four shapes and confirm each of the following resolves as `good` when linked to (currently all would be `broken`):
```markdown
# Doc
<a name="custom-anchor"></a>
## Some Heading
<a id="another-anchor"></a>

<h2 id="raw-html-heading">Raw HTML Heading</h2>

Some text with an inline <a id="inline-anchor"></a> anchor.

## Some <a id="heading-embedded-anchor"></a> Heading

[a](#custom-anchor) [b](#another-anchor) [c](#raw-html-heading) [d](#inline-anchor) [e](#heading-embedded-anchor) [f](#some-heading)
```
Also re-run the existing fixture-based scenarios from the original build (duplicate headings still get `-1`/`-2` suffixes correctly; a link to a genuinely missing anchor is still reported `broken`; regular Markdown links/images are unaffected) to confirm no regression. Run `md-health` against the fixture directory and inspect the report table directly (don't just check exit code, which is always 0 regardless).
