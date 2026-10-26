"""The dashboard as static files, for hosting it without the local server.

The page is the same as `fantasy serve`; the data the server would answer
with (the view and both report versions) goes into static/data.js instead.
Settings and the trade evaluator need the server, so the page hides them
when it finds that file; Refresh asks GitHub to run the workflow instead.
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


class ExportError(Exception):
    pass


def export_site(app: FantasyApp, out: Path) -> Path:
    view = app.view()
    if view is None:
        raise ExportError("No snapshot yet: run `fantasy refresh` first.")
    data = {
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
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out / "static", ignore=shutil.ignore_patterns("index.html", "sw.js"))
    # The service worker sits at the root so it covers the whole page.
    shutil.copy(STATIC / "sw.js", out / "sw.js")
    payload = json.dumps(data, allow_nan=False, ensure_ascii=False)
    (out / "static" / "data.js").write_text(
        f"window.FANTASY_STATIC = {payload};\n", encoding="utf-8"
    )
    # Polled by the open page, which reloads itself when a newer export is up.
    (out / "static" / "version.json").write_text(
        json.dumps({"exported_at": data["exported_at"]}), encoding="utf-8"
    )
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    page = page.replace(
        '<meta name="viewport"',
        '<meta name="robots" content="noindex">\n  <meta name="viewport"',
        1,
    ).replace(
        '<script src="/static/app.js"></script>',
        '<script src="/static/data.js"></script>\n  <script src="/static/app.js"></script>',
        1,
    )
    # Relative paths, so the page also works from a subfolder such as
    # https://<user>.github.io/<repo>/.
    page = page.replace('"/static/', '"static/')
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "_headers").write_text(HEADERS, encoding="utf-8")
    return out
