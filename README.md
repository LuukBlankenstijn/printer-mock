# IPP Sink

A Docker container that pretends to be an IPP (network) printer. Every job
it receives is rendered to PDF and shown in a small web UI, so you can
inspect what a client is actually sending.

Built on CUPS + `cups-pdf` + a tiny Flask web UI — no custom IPP parsing.

## Ports

| Port | Purpose                                                   |
|------|-----------------------------------------------------------|
| 631  | IPP endpoint (and the CUPS admin web UI at `http://host:631/`) |
| 8080 | Captured-jobs web UI                                      |

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

## Config

Environment variables on the container:

| Variable           | Default           | Purpose                          |
|--------------------|-------------------|----------------------------------|
| `PRINTER_NAME`     | `SinkPrinter`     | Queue name (and part of IPP URL) |
| `PRINTER_INFO`     | `IPP Sink (dev)`  | Human-readable description       |
| `PRINTER_LOCATION` | `Docker`          | Location string                  |

Captured jobs live in the `ipp-jobs` volume
(`/var/spool/cups-pdf/jobs` inside the container).

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
