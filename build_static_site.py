import datetime as dt
import json
import os

from dashboard import HTML_PAGE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")


def export_static_site(scan_res: dict, report_res: dict) -> str:
    """Export static GitHub Pages bundle (docs/index.html + docs/data.json)."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    now_col = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")

    payload = {
        "generated_col": now_col,
        "scan": scan_res,
        "report": report_res,
    }
    with open(os.path.join(DOCS_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    static_html = HTML_PAGE.replace("const STATIC_MODE = false;", "const STATIC_MODE = true;")
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(static_html)

    nojekyll = os.path.join(DOCS_DIR, ".nojekyll")
    if not os.path.exists(nojekyll):
        with open(nojekyll, "w", encoding="utf-8") as f:
            f.write("")

    return DOCS_DIR
