"""
Web UI for the IPP sink printer.

Lists PDFs produced by cups-pdf in /var/spool/cups-pdf/jobs and lets you
view / download them. Also surfaces any currently-queued CUPS jobs via
`lpstat` so you can see in-flight submissions.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, render_template_string, send_file, redirect, url_for

JOBS_DIR = Path(os.environ.get("JOBS_DIR", "/var/spool/cups-pdf/jobs"))
PRINTER_NAME = os.environ.get("PRINTER_NAME", "SinkPrinter")

app = Flask(__name__)


def list_jobs():
    """Return a list of {name, size, mtime, path} for captured files, newest first.

    We list *all* files, not just .pdf, so that if cups-pdf is misbehaving
    and writing something unexpected (intermediate .ps files, .job files,
    etc.) we can still see it here for debugging.
    """
    if not JOBS_DIR.exists():
        return []
    entries = []
    for p in JOBS_DIR.iterdir():
        if not p.is_file():
            continue
        st = p.stat()
        entries.append({
            "name": p.name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime),
            "path": p,
            "is_pdf": p.suffix.lower() == ".pdf",
        })
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries


def active_cups_jobs():
    """Query CUPS for any jobs currently in the queue (pending / processing)."""
    try:
        out = subprocess.run(
            ["lpstat", "-W", "not-completed", "-o"],
            capture_output=True, text=True, timeout=3,
        )
        lines = [l for l in out.stdout.splitlines() if l.strip()]
        return lines
    except Exception:
        return []


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IPP Sink &mdash; Captured Jobs</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #171a21;
    --border: #262b36;
    --text: #e6e8ec;
    --muted: #8a8f9a;
    --accent: #6ea8fe;
    --accent-hover: #8db8ff;
    --danger: #ef6b6b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.5;
  }
  header {
    padding: 24px 32px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { margin: 0; font-size: 20px; font-weight: 600; }
  header .meta { color: var(--muted); font-size: 13px; font-family: ui-monospace, monospace; }
  main { padding: 24px 32px; max-width: 1100px; margin: 0 auto; }
  .panel {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 20px;
  }
  .panel h2 { margin: 0 0 12px; font-size: 14px; text-transform: uppercase;
              letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px;
       text-transform: uppercase; letter-spacing: 0.04em; }
  tr:last-child td { border-bottom: none; }
  td.name { font-family: ui-monospace, "SF Mono", Menlo, monospace;
            word-break: break-all; }
  td.actions a {
    color: var(--accent); text-decoration: none; margin-right: 12px;
  }
  td.actions a:hover { color: var(--accent-hover); text-decoration: underline; }
  .empty { color: var(--muted); font-style: italic; padding: 12px 0; }
  code { background: #0b0d12; padding: 2px 6px; border-radius: 4px;
         font-size: 13px; color: #c8ccd4; }
  .ipp-url { font-family: ui-monospace, monospace; color: var(--accent); }
</style>
</head>
<body>
<header>
  <h1>🖨️  IPP Sink</h1>
  <div class="meta">queue: <span class="ipp-url">{{ printer }}</span></div>
</header>
<main>
  <div class="panel">
    <h2>Submit jobs here</h2>
    <p style="margin:0;color:var(--muted);font-size:14px;">
      Point any IPP client at
      <code class="ipp-url">ipp://HOST:631/printers/{{ printer }}</code>
      &mdash; every job is silently accepted and rendered as PDF below.
    </p>
  </div>

  {% if active %}
  <div class="panel">
    <h2>In queue ({{ active|length }})</h2>
    <pre style="margin:0;color:var(--muted);font-family:ui-monospace,monospace;font-size:13px;">{{ active|join('\n') }}</pre>
  </div>
  {% endif %}

  <div class="panel">
    <h2>Captured jobs ({{ jobs|length }})</h2>
    {% if not jobs %}
      <div class="empty">No jobs captured yet. Send a print job to the queue to see it here.</div>
    {% else %}
    <table>
      <thead>
        <tr><th>Filename</th><th>Received</th><th>Size</th><th></th></tr>
      </thead>
      <tbody>
        {% for j in jobs %}
        <tr>
          <td class="name">{{ j.name }}</td>
          <td>{{ j.mtime.strftime('%Y-%m-%d %H:%M:%S') }}</td>
          <td>{{ j.size_h }}</td>
          <td class="actions">
            {% if j.is_pdf %}
            <a href="{{ url_for('view_job', name=j.name) }}" target="_blank">View</a>
            {% else %}
            <span style="color:var(--muted)" title="Not a PDF — download to inspect">—</span>
            {% endif %}
            <a href="{{ url_for('download_job', name=j.name) }}">Download</a>
            <a href="{{ url_for('delete_job', name=j.name) }}"
               style="color:var(--danger)"
               onclick="return confirm('Delete {{ j.name }}?')">Delete</a>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </div>
</main>
</body>
</html>
"""


@app.route("/")
def index():
    jobs = list_jobs()
    for j in jobs:
        j["size_h"] = human_size(j["size"])
    return render_template_string(
        INDEX_HTML,
        jobs=jobs,
        active=active_cups_jobs(),
        printer=PRINTER_NAME,
    )


def _resolve(name):
    """Safely resolve a requested job filename within JOBS_DIR."""
    # Reject path separators / traversal outright
    if "/" in name or "\\" in name or name.startswith("."):
        abort(400)
    path = (JOBS_DIR / name).resolve()
    if JOBS_DIR.resolve() not in path.parents:
        abort(400)
    if not path.exists() or not path.is_file():
        abort(404)
    return path


@app.route("/jobs/<name>")
def view_job(name):
    path = _resolve(name)
    return send_file(path, mimetype="application/pdf")


@app.route("/jobs/<name>/download")
def download_job(name):
    path = _resolve(name)
    # Let Flask guess the mimetype from the filename
    return send_file(path, as_attachment=True, download_name=name)


@app.route("/jobs/<name>/delete")
def delete_job(name):
    path = _resolve(name)
    path.unlink()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
