# Printer Sink

A Docker container that pretends to be a network printer on two protocols
at once — **IPP** (renders to PDF via CUPS) and **ESC/POS** (raw TCP on
port 9100, the JetDirect / receipt-printer protocol). Every job it
receives is captured and shown in a small web UI with separate tabs, so
you can inspect what a client is actually sending.

Built on CUPS + `cups-pdf` + a tiny Flask web UI + an in-process TCP sink.

## Ports

| Port | Purpose                                                   |
|------|-----------------------------------------------------------|
| 631  | IPP endpoint (and the CUPS admin web UI at `http://host:631/`) |
| 8080 | Captured-jobs web UI (two tabs: IPP / PDF, ESC/POS)       |
| 9100 | ESC/POS raw TCP endpoint                                  |

## Run

```sh
docker compose up --build -d
```

Then open **http://localhost:8080/** to see captured jobs.

## Point a client at it

The IPP URL is:

```
ipp://HOST:631/printers/SinkPrinter
```

- **macOS / Linux**: System Settings → Printers → Add → IPP → paste URL.
  Pick "Generic PDF Printer" or "IPP Everywhere" as the driver.
- **Windows**: Add printer → The printer I want isn't listed → Select a
  shared printer by name → `http://HOST:631/printers/SinkPrinter`.
- **`ipptool` / CLI**:
  ```sh
  ipptool -tv -f somefile.pdf \
      ipp://localhost:631/printers/SinkPrinter \
      print-job.test
  ```
- **`lp` from another machine with CUPS**:
  ```sh
  lp -h HOST:631 -d SinkPrinter somefile.pdf
  ```

Every submitted job appears in the web UI as a PDF you can view or download.

## Send ESC/POS to it

ESC/POS thermal-printer clients should target raw TCP **port 9100**.
Every TCP connection becomes one captured job.

- **`python-escpos`**:
  ```python
  from escpos.printer import Network
  p = Network("HOST", 9100)
  p.text("Hello world\n")
  p.set(align="center", bold=True, double_height=True)
  p.text("RECEIPT\n")
  p.cut()
  ```
- **`nc` / shell**:
  ```sh
  printf '\x1b@\x1ba\x01RECEIPT\n\x1bE\x01TOTAL: 9.99\x1bE\x00\n\n\n\x1dV\x00' \
      | nc HOST 9100
  ```
- Any node / Go / Rust ESC/POS lib with a "Network" or TCP driver works.

Open the **ESC/POS** tab in the web UI to see captured jobs rendered as a
receipt (text, bold, underline, alignment, double-size, cuts, raster
images). The raw `.bin` is also downloadable.

## Config

Environment variables on the container:

| Variable           | Default           | Purpose                          |
|--------------------|-------------------|----------------------------------|
| `PRINTER_NAME`     | `SinkPrinter`     | Queue name (and part of IPP URL) |
| `PRINTER_INFO`     | `IPP Sink (dev)`  | Human-readable description       |
| `PRINTER_LOCATION` | `Docker`          | Location string                  |
| `ESCPOS_PORT`      | `9100`            | TCP port the ESC/POS sink listens on |

Captured jobs live in two volumes:
- `ipp-jobs`    → `/var/spool/cups-pdf/jobs` (PDFs from IPP)
- `escpos-jobs` → `/var/spool/escpos-jobs`   (raw `.bin` ESC/POS streams)

## Caveats

- This is a dev tool. The CUPS admin UI has auth disabled and binds to all
  interfaces — **don't expose it to an untrusted network.**
- `cups-pdf` filters jobs through Ghostscript, so what you see is the
  rasterized/rendered result, not necessarily the exact bytes the client
  sent. If you need the raw PostScript/PDF the client uploaded, look in
  `/var/spool/cups/` while a job is in-flight, or swap the backend for
  a null filter.
- No mDNS/Bonjour advertising is set up, so the printer won't auto-appear
  in AirPrint-style discovery. Add it manually by URL.
