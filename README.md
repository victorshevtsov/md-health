# md-health

`md-health` recursively scans a directory tree of Markdown files, extracts every
link and image reference, validates them, and prints a colored report.

## Install

```bash
pip install -e .
```

Requires Python 3.10+.

## Usage

```bash
md-health            # scan the current directory
md-health path/to/docs
```

## What gets checked

- Regular links `[text](url)` and reference-style links (`[text][ref]`, including
  unused `[ref]: url` definitions).
- Image sources `![alt](url)`, including relative image paths.
- Pure fragment links (`[text](#section)`) and links with anchors
  (`[text](file.md#section)`).
- **Local links/images**: the target file must exist on disk (resolved relative
  to the Markdown file containing the link). If an anchor is present, a
  matching heading must exist in the target file (ATX `#` and Setext
  `===`/`---` headings are both supported, normalized using GitHub-style
  anchor slugs).
- **Remote `http://`/`https://` links**: checked with a `HEAD` request
  (falling back to `GET` on `405`), following up to 3 redirects, with a 1
  second timeout and 3 concurrent requests. A final 2xx/3xx status is good; a
  403 is reported as **unknown** (not broken); anything else (other 4xx/5xx,
  timeouts, connection/SSL errors, too many redirects) is **broken**.
- **Unsupported schemes** (`mailto:`, `tel:`, `ftp:`, `file:`, etc.) are
  reported as **unsupported** and not validated.

Links inside fenced code blocks or inline code spans are ignored.

## What gets ignored

The following directories are always skipped when found:
`.git`, `.hg`, `.svn`, `node_modules`, `__pycache__`, `.venv`, `venv`, `env`,
`dist`, `build`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`,
`site-packages`. Only the ones actually encountered during the scan are
listed in the report.

## Exit code

`md-health` always exits `0`, even when broken/unknown/unsupported links are
found. It's a reporting tool, not a CI gate — don't rely on its exit code in
a `set -e` pipeline.

## Limitations

- No configuration file, no JSON/machine-readable output.
- Remote concurrency (3), timeout (1s), and max redirects (3) are hard-coded.
- No authentication, custom headers, or domain allow/deny lists.
- Markdown is parsed as plain CommonMark; GFM extensions (tables,
  strikethrough, etc.) aren't specially parsed, though links inside them are
  still found via paragraph fallback.

## Development

```bash
pip install -e ".[dev]"
pytest
```
