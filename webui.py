"""
Web UI for the sink printer.

Two capture pipelines, two tabs:
  - IPP / PDF:  jobs CUPS rendered into /var/spool/cups-pdf/jobs
  - ESC/POS:    raw byte streams captured from TCP port 9100
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, redirect, render_template_string, send_file, url_for

import escpos_parser
import escpos_server

JOBS_DIR = Path(os.environ.get("JOBS_DIR", "/var/spool/cups-pdf/jobs"))
ESCPOS_DIR = Path(os.environ.get("ESCPOS_DIR", "/var/spool/escpos-jobs"))
PRINTER_NAME = os.environ.get("PRINTER_NAME", "SinkPrinter")
ESCPOS_PORT = int(os.environ.get("ESCPOS_PORT", "9100"))

app = Flask(__name__)


def _list_files(base: Path) -> list[dict]:
    if not base.exists():
        return []
    out = []
    for p in base.iterdir():
        if not p.is_file():
            continue
        st = p.stat()
        out.append({
            "name": p.name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime),
            "is_pdf": p.suffix.lower() == ".pdf",
        })
    out.sort(key=lambda e: e["mtime"], reverse=True)
    return out


def list_pdf_jobs():
    return _list_files(JOBS_DIR)


def list_escpos_jobs():
    return _list_files(ESCPOS_DIR)


def active_cups_jobs():
    """Query CUPS for any jobs currently in the queue (pending / processing)."""
    try:
        out = subprocess.run(
            ["lpstat", "-W", "not-completed", "-o"],
            capture_output=True, text=True, timeout=3,
        )
        return [l for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return []


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _resolve_in(base: Path, name: str) -> Path:
    """Safely resolve a requested filename within `base`."""
    if "/" in name or "\\" in name or name.startswith("."):
        abort(400)
    path = (base / name).resolve()
    if base.resolve() not in path.parents:
        abort(400)
    if not path.exists() or not path.is_file():
        abort(404)
    return path


PAGE_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Printer Sink &mdash; {{ tab_title }}</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #262b36;
    --text: #e6e8ec; --muted: #8a8f9a; --accent: #6ea8fe;
    --accent-hover: #8db8ff; --danger: #ef6b6b;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.5; }
  header { padding: 20px 32px; border-bottom: 1px solid var(--border);
           display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 20px; font-weight: 600; }
  .nav { display: flex; gap: 4px; }
  .nav a { color: var(--muted); text-decoration: none; padding: 8px 14px;
           border-radius: 6px; font-size: 13px; font-weight: 500;
           border: 1px solid transparent; }
  .nav a:hover { color: var(--text); background: var(--panel); }
  .nav a.active { color: var(--text); background: var(--panel); border-color: var(--border); }
  .meta { margin-left: auto; color: var(--muted); font-size: 13px;
          font-family: ui-monospace, monospace; }
  main { padding: 24px 32px; max-width: 1100px; margin: 0 auto; }
  .panel { background: var(--panel); border: 1px solid var(--border);
           border-radius: 8px; padding: 16px 20px; margin-bottom: 20px; }
  .panel h2 { margin: 0 0 12px; font-size: 14px; text-transform: uppercase;
              letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }
  .panel p { margin: 0; color: var(--muted); font-size: 14px; }
  .panel p + p { margin-top: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px;
       text-transform: uppercase; letter-spacing: 0.04em; }
  tr:last-child td { border-bottom: none; }
  td.name { font-family: ui-monospace, "SF Mono", Menlo, monospace; word-break: break-all; }
  td.actions a { color: var(--accent); text-decoration: none; margin-right: 12px; }
  td.actions a:hover { color: var(--accent-hover); text-decoration: underline; }
  .empty { color: var(--muted); font-style: italic; padding: 12px 0; }
  code { background: #0b0d12; padding: 2px 6px; border-radius: 4px;
         font-size: 13px; color: #c8ccd4; }
  .url { font-family: ui-monospace, monospace; color: var(--accent); }
</style>
</head>
<body>
<header>
  <h1>🖨️  Printer Sink</h1>
  <nav class="nav">
    <a href="{{ url_for('index') }}" class="{% if tab=='ipp' %}active{% endif %}">IPP / PDF</a>
    <a href="{{ url_for('escpos_index') }}" class="{% if tab=='escpos' %}active{% endif %}">ESC/POS</a>
  </nav>
  <div class="meta">{{ subtitle }}</div>
</header>
<main>
{% if tab == 'ipp' %}
  <div class="panel">
    <h2>IPP submission</h2>
    <p>
      Point any IPP client at
      <code class="url">ipp://HOST:631/printers/{{ printer }}</code>
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
    <h2>Captured PDF jobs ({{ jobs|length }})</h2>
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
{% else %}
  <div class="panel">
    <h2>ESC/POS submission</h2>
    <p>
      Send raw ESC/POS bytes over TCP to
      <code class="url">HOST:{{ escpos_port }}</code>
      (the standard JetDirect / RAW port). Each TCP connection becomes one job.
    </p>
    <p>
      Quick test: <code>cat receipt.bin | nc HOST {{ escpos_port }}</code>
      &nbsp;&middot;&nbsp;
      or use <code>python-escpos</code> with the
      <code>Network("HOST", {{ escpos_port }})</code> driver.
    </p>
  </div>

  <div class="panel">
    <h2>Captured ESC/POS jobs ({{ jobs|length }})</h2>
    {% if not jobs %}
      <div class="empty">No ESC/POS jobs captured yet. Connect a client to port {{ escpos_port }}.</div>
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
            <a href="{{ url_for('view_escpos', name=j.name) }}">View</a>
            <a href="{{ url_for('download_escpos', name=j.name) }}">Download</a>
            <a href="{{ url_for('delete_escpos', name=j.name) }}"
               style="color:var(--danger)"
               onclick="return confirm('Delete {{ j.name }}?')">Delete</a>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </div>
{% endif %}
</main>
</body>
</html>
"""


VIEW_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ name }} &mdash; ESC/POS preview</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #262b36;
    --text: #e6e8ec; --muted: #8a8f9a; --accent: #6ea8fe;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  header { padding: 14px 24px; border-bottom: 1px solid var(--border);
           display: flex; align-items: center; gap: 16px; font-size: 14px; }
  header a { color: var(--accent); text-decoration: none; }
  header a:hover { text-decoration: underline; }
  header .filename { color: var(--muted); font-family: ui-monospace, monospace; font-size: 13px; }
  main { padding: 32px 16px; display: flex; justify-content: center; }

  /* 80mm thermal receipt feel. 384px ≈ 80mm at 4.8 px/mm */
  .paper {
    background: #fdfcf6; color: #111;
    width: 384px; padding: 24px 16px;
    font-family: ui-monospace, "Courier New", monospace;
    font-size: 14px; line-height: 1.35;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
    border-radius: 2px;
  }
  .paper .line { min-height: 1.35em; white-space: pre-wrap; word-break: break-word; }
  .paper .align-left   { text-align: left; }
  .paper .align-center { text-align: center; }
  .paper .align-right  { text-align: right; }
  .paper .note { color: #888; font-style: italic; font-size: 12px; margin: 4px 0; }
  .paper hr.cut {
    border: none; border-top: 2px dashed #b9b3a0;
    margin: 16px -16px 16px; position: relative;
  }
  .paper hr.cut::before {
    content: "✂  paper cut"; position: absolute;
    left: 50%; top: -10px; transform: translateX(-50%);
    background: #fdfcf6; padding: 0 6px;
    color: #999; font-size: 10px; font-style: italic;
  }
  .paper .img-wrap { margin: 6px 0; }
  .paper .img-wrap.align-center { text-align: center; }
  .paper .img-wrap.align-right  { text-align: right; }
  .paper img { max-width: 100%; height: auto; }
</style>
</head>
<body>
<header>
  <a href="{{ url_for('escpos_index') }}">&larr; Back</a>
  <span class="filename">{{ name }}</span>
  <span style="margin-left:auto;">
    <a href="{{ url_for('download_escpos', name=name) }}">Download raw .bin</a>
  </span>
</header>
<main>
  <div class="paper">{{ rendered|safe }}</div>
</main>
</body>
</html>
"""


@app.route("/")
def index():
    jobs = list_pdf_jobs()
    for j in jobs:
        j["size_h"] = human_size(j["size"])
    return render_template_string(
        PAGE_HTML,
        tab="ipp",
        tab_title="IPP / PDF",
        subtitle="queue: " + PRINTER_NAME,
        jobs=jobs,
        active=active_cups_jobs(),
        printer=PRINTER_NAME,
        escpos_port=ESCPOS_PORT,
    )


@app.route("/escpos")
def escpos_index():
    jobs = list_escpos_jobs()
    for j in jobs:
        j["size_h"] = human_size(j["size"])
    return render_template_string(
        PAGE_HTML,
        tab="escpos",
        tab_title="ESC/POS",
        subtitle=f"raw TCP port {ESCPOS_PORT}",
        jobs=jobs,
        active=[],
        printer=PRINTER_NAME,
        escpos_port=ESCPOS_PORT,
    )


@app.route("/jobs/<name>")
def view_job(name):
    return send_file(_resolve_in(JOBS_DIR, name), mimetype="application/pdf")


@app.route("/jobs/<name>/download")
def download_job(name):
    return send_file(_resolve_in(JOBS_DIR, name),
                     as_attachment=True, download_name=name)


@app.route("/jobs/<name>/delete")
def delete_job(name):
    _resolve_in(JOBS_DIR, name).unlink()
    return redirect(url_for("index"))


@app.route("/escpos/<name>")
def view_escpos(name):
    path = _resolve_in(ESCPOS_DIR, name)
    rendered = escpos_parser.render_html(path.read_bytes())
    return render_template_string(VIEW_HTML, name=name, rendered=rendered)


@app.route("/escpos/<name>/download")
def download_escpos(name):
    return send_file(_resolve_in(ESCPOS_DIR, name),
                     as_attachment=True, download_name=name,
                     mimetype="application/octet-stream")


@app.route("/escpos/<name>/delete")
def delete_escpos(name):
    _resolve_in(ESCPOS_DIR, name).unlink()
    return redirect(url_for("escpos_index"))


if __name__ == "__main__":
    ESCPOS_DIR.mkdir(parents=True, exist_ok=True)
    escpos_server.start(ESCPOS_DIR, port=ESCPOS_PORT)
    app.run(host="0.0.0.0", port=8080, debug=False)
