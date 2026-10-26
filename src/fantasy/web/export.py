"""The dashboard as static files, for hosting it without the local server.

The page is the same as `fantasy serve`. Two ways to give it its data:

- `export_site` puts the data (the view and the report versions) into
  static/data.js next to the page: one folder that works anywhere.
- `export_shell` writes the page alone, set to read data.json from a branch
  of the GitHub repository, and `export_data` writes that data.json. GitHub
  Pages then only needs a new deployment when the page's code changes; the
  hourly run just replaces the file on the branch.

Settings and the trade evaluator need the server, so the page hides them;
Refresh asks GitHub to run the workflow instead.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fantasy.app import FantasyApp
from fantasy.web.server import STATIC

HEADERS = """/*
  X-Robots-Tag: noindex
  Cache-Control: no-store
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
"""

WORKFLOW = "daily.yml"
DATA_BRANCH = "data"


class ExportError(Exception):
    pass


def export_site(app: FantasyApp, out: Path) -> Path:
    payload = json.dumps(_payload(app), allow_nan=False, ensure_ascii=False)
    _write_page(out, "data.js")
    (out / "static" / "data.js").write_text(
        f"window.FANTASY_STATIC = {payload};\n", encoding="utf-8"
    )
    # Polled by the open page, which reloads itself when a newer export is up.
    (out / "static" / "version.json").write_text(
        json.dumps({"exported_at": json.loads(payload)["exported_at"]}), encoding="utf-8"
    )
    return out


def export_shell(out: Path, repo: str | None = None) -> Path:
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise ExportError("The page needs the GitHub repository (owner/name) it reads data from.")
    _write_page(out, "hosted.js")
    hosted = {
        "repo": repo,
        "branch": DATA_BRANCH,
        "workflow": WORKFLOW,
        "ref": os.environ.get("GITHUB_REF_NAME") or "main",
    }
    (out / "static" / "hosted.js").write_text(
        f"window.FANTASY_HOSTED = {json.dumps(hosted)};\n", encoding="utf-8"
    )
    return out


def export_data(app: FantasyApp, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "data.json"
    path.write_text(
        json.dumps(_payload(app), allow_nan=False, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _payload(app: FantasyApp) -> dict:
    view = app.view()
    if view is None:
        raise ExportError("No snapshot yet: run `fantasy refresh` first.")
    return {
        "view": view,
        "demo": app.demo,
        "report": {
            "full": app.report(),
            "compact": app.report(compact=True),
            "brief": app.report(brief=True),
        },
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        # Set when GitHub Actions builds the page: the page's Refresh starts
        # this workflow again.
        "repo": os.environ.get("GITHUB_REPOSITORY"),
        "workflow": WORKFLOW,
        "ref": os.environ.get("GITHUB_REF_NAME") or "main",
    }


def _write_page(out: Path, data_script: str) -> None:
    """The page and its assets, loading `data_script` before the app."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out / "static", ignore=shutil.ignore_patterns("index.html", "sw.js"))
    # The service worker sits at the root so it covers the whole page.
    shutil.copy(STATIC / "sw.js", out / "sw.js")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    page = page.replace(
        '<meta name="viewport"',
        '<meta name="robots" content="noindex">\n  <meta name="viewport"',
        1,
    ).replace(
        '<script src="/static/app.js"></script>',
        f'<script src="/static/{data_script}"></script>\n  <script src="/static/app.js"></script>',
        1,
    )
    # Relative paths, so the page also works from a subfolder such as
    # https://<user>.github.io/<repo>/.
    page = page.replace('"/static/', '"static/')
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "_headers").write_text(HEADERS, encoding="utf-8")
