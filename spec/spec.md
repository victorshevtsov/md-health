**Task: Build a Python CLI tool named `md-health`**

Create a command-line tool called `md-health` that recursively scans a directory tree for Markdown (`.md`) files, extracts all links and image sources, validates them, and prints a clear colored report.

### Core requirements

**Input / CLI**
- Written in Python 3.10+.
- Installable package with a console entry point `md-health`.
- Accepts an optional target directory (default: current working directory).
- Recursively walks the directory tree.
- Default ignored directories (hard-coded):  
  `.git`, `.hg`, `.svn`, `node_modules`, `__pycache__`, `.venv`, `venv`, `env`, `dist`, `build`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `site-packages`.  
  Print the list of skipped directories that were actually encountered.
- No configuration file.
- No JSON output mode.
- Process must always exit with code 0 (even when broken/unknown/unsupported links are found).

**What to extract and check**
- Regular links: `[text](url)` and reference-style links.
- Image sources: `![alt](url)` — including **relative image paths** (e.g. `![logo](../images/logo.png)`, `![icon](./assets/icon.svg)`).
- Pure fragment links: `[text](#section)`.
- Local relative / absolute file links (including those with anchors).
- Remote `http://` and `https://` URLs.
- Ignore links that appear only inside fenced code blocks or inline code.

**Validation rules**
- **Local links and local images** (including pure fragments, links with anchors, and relative image paths):
  - Resolve the path relative to the Markdown file that contains the link/image.
  - Check that the target file exists on disk.
  - If an anchor is present (`#...`), verify that a corresponding heading exists in the target Markdown file (support both ATX `#` headings and Setext-style headings; normalize heading text to GitHub-style anchors).
  - Relative image paths are treated exactly like relative links for existence checking.
- **Remote links** (`http://` and `https://` only):
  - Issue a `HEAD` request first.
  - Fall back to `GET` if the server returns 405.
  - Follow redirects (maximum 3 redirects, hard-coded).
  - Timeout: 1 second (hard-coded default).
  - Concurrency: 3 simultaneous requests (hard-coded default).
  - **Success**: final status 2xx or 3xx.
  - **403 Forbidden** → count and report as **unknown** (never as broken).
  - All other non-success outcomes (other 4xx, 5xx, timeouts, SSL errors, connection errors, too many redirects, etc.) → **broken**.
  - No authentication, no custom headers, no domain exclusions.
- **Unsupported schemes** (`mailto:`, `tel:`, `ftp://`, `file://`, and any other non-`http`/`https`/local scheme):
  - Do not attempt to validate them.
  - Report them as **unsupported**.
- Collect a clear reason for every non-success result.

**Output (use the `rich` library)**
- Colored summary showing:
  - Total links found
  - Good / broken / **unknown** / unsupported counts
  - Breakdown by type (local vs remote vs unsupported, and optionally images vs regular links)
- List of directories that were skipped because they matched the default ignore list.
- Detailed section (only when there are non-good links) containing for each broken / unknown / unsupported link:
  - Source Markdown file + line number
  - Original link / image markup or URL
  - Resolved target (when applicable)
  - Status / reason (`unsupported scheme`, `file not found`, `HTTP 404`, `HTTP 403 (unknown)`, `timeout`, etc.)
- Clean, readable terminal output. Respect `NO_COLOR` / non-TTY by falling back to plain text.

**Technical expectations**
- Prefer a real Markdown parser (e.g. `markdown-it-py` or `mistune`) over brittle regexes.
- Use `httpx` or `aiohttp` (or `requests` + `concurrent.futures`) for remote checks; keep concurrency at 3.
- Type hints throughout.
- Suggested project layout:
  ```
  md_health/
    __init__.py
    cli.py
    checker.py
    parser.py
    reporter.py
  pyproject.toml
  README.md
  ```
- `pyproject.toml` must define the `md-health` entry point and list dependencies.
- Include a short README explaining usage.

**Out of scope**
- No support for other markup formats.
- No automatic fixing or rewriting of links.
- No configuration file.
- No JSON / machine-readable report.
- No authentication or custom headers.
- No domain allow/deny lists.
- Exit code is always 0.

**Acceptance criteria**
1. Running `md-health` (or `md-health .`) on a documentation tree of a few hundred `.md` files produces a correct colored report.
2. Local missing files, missing anchors, and pure-fragment failures are detected.
3. Remote broken links (404, timeout, 5xx, etc.) are reported as broken.
4. `403 Forbidden` responses are counted and reported as **unknown** (not broken).
5. Image sources (including relative image paths) are checked the same way as regular links.
6. Links with unsupported schemes are reported as **unsupported**.
7. Ignored directories are skipped and listed in the output.
8. The tool never exits with a non-zero status because of broken, unknown, or unsupported links.
9. Output is pleasant and informative when using `rich`.

Please implement the full working tool, including packaging, so that after `pip install -e .` the command `md-health` is available.
