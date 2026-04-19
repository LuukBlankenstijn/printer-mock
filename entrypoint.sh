#!/bin/bash
set -euo pipefail

PRINTER_NAME="${PRINTER_NAME:-SinkPrinter}"
PRINTER_INFO="${PRINTER_INFO:-IPP Sink Printer}"
PRINTER_LOCATION="${PRINTER_LOCATION:-Docker}"

# Point cups cli tools (lpadmin, lpstat) at our local socket explicitly.
# Without this they may try a distro-specific default path and fail with
# "Bad file descriptor" even when cupsd is running fine.
export CUPS_SERVER=/run/cups/cups.sock

log() { echo "[ipp-sink] $*"; }

# Sanity-check cupsd.conf before starting. If this fails we bail loudly
# rather than letting lpadmin spin on a dead server.
log "Validating cupsd.conf..."
if ! cupsd -t; then
    log "FATAL: cupsd.conf failed validation. Printing it for diagnosis:"
    cat -n /etc/cups/cupsd.conf
    exit 1
fi

# Start cupsd in the background while we register the queue. After setup
# is done, we'll start the web UI and then bring cupsd back to foreground
# by `wait`-ing on it. That way cupsd gets SIGTERM properly on container stop.
log "Starting cupsd..."
/usr/sbin/cupsd -f &
CUPSD_PID=$!

# Forward SIGTERM/SIGINT to both processes on container stop.
cleanup() {
    log "Shutting down..."
    kill "$CUPSD_PID" 2>/dev/null || true
    kill "${WEBUI_PID:-}" 2>/dev/null || true
    wait
    exit 0
}
trap cleanup TERM INT

# Wait for the cups unix socket to become accepting.
log "Waiting for cupsd to accept connections..."
for i in $(seq 1 50); do
    if lpstat -r >/dev/null 2>&1; then
        log "cupsd is up (after ${i} tries)"
        break
    fi
    # Fail fast if cupsd has already died
    if ! kill -0 "$CUPSD_PID" 2>/dev/null; then
        log "FATAL: cupsd died during startup. Check logs above."
        exit 1
    fi
    sleep 0.2
done

if ! lpstat -r >/dev/null 2>&1; then
    log "FATAL: cupsd never became ready"
    exit 1
fi

# Find the cups-pdf PPD. Debian moves it around between releases.
PPD=""
for candidate in \
    /usr/share/ppd/cups-pdf/CUPS-PDF_opt.ppd \
    /usr/share/ppd/cups-pdf/CUPS-PDF.ppd \
    /usr/share/cups/model/CUPS-PDF_opt.ppd \
    /usr/share/cups/model/CUPS-PDF.ppd
do
    if [ -f "$candidate" ]; then
        PPD="$candidate"
        break
    fi
done

if [ -z "$PPD" ]; then
    log "Could not find a cups-pdf PPD file. Falling back to 'everywhere' model."
    MODEL_ARG=(-m everywhere)
else
    log "Using PPD: $PPD"
    MODEL_ARG=(-P "$PPD")
fi

# Register the virtual PDF queue.
if ! lpstat -p "$PRINTER_NAME" >/dev/null 2>&1; then
    log "Registering queue '$PRINTER_NAME'..."
    lpadmin -p "$PRINTER_NAME" \
            -E \
            -v cups-pdf:/ \
            -D "$PRINTER_INFO" \
            -L "$PRINTER_LOCATION" \
            "${MODEL_ARG[@]}" \
            -o printer-is-shared=true
    cupsenable "$PRINTER_NAME" || true
    cupsaccept "$PRINTER_NAME" || true
else
    log "Queue '$PRINTER_NAME' already exists"
fi

cat <<EOF
===========================================
  IPP Sink Printer ready
    Queue:    $PRINTER_NAME
    IPP URL:  ipp://<host>:631/printers/$PRINTER_NAME
    CUPS UI:  http://<host>:631/
    Jobs UI:  http://<host>:8080/
===========================================
EOF

# Hand off: web UI in background, wait on cupsd as the main process.
log "Starting web UI on :8080"
python3 /opt/webui/webui.py &
WEBUI_PID=$!

# Wait on cupsd. If it exits, we exit too (docker will restart if configured).
wait "$CUPSD_PID"
