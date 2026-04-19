FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# CUPS + the PDF virtual printer + Python/Flask for the web UI.
RUN apt-get update && apt-get install -y --no-install-recommends \
        cups \
        cups-pdf \
        cups-filters \
        printer-driver-cups-pdf \
        python3 \
        python3-flask \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- cupsd config -------------------------------------------------------
# Replace the stock cupsd.conf entirely rather than trying to patch it.
COPY cupsd.conf /etc/cups/cupsd.conf
RUN chown root:lp /etc/cups/cupsd.conf && chmod 0640 /etc/cups/cupsd.conf

# --- cups-pdf config ----------------------------------------------------
# Use the stock Debian cups-pdf.conf and only patch the output path.
# Stock behaviour: writes to /var/spool/cups-pdf/ANONYMOUS for anonymous
# jobs, which is exactly what we want for a sink printer — remote print
# clients have no Unix user account here. We just redirect that to a
# predictable flat directory and disable per-user subdirs.
RUN sed -i \
        -e 's|^#\?\s*Out\s\+.*|Out /var/spool/cups-pdf/jobs|' \
        -e 's|^#\?\s*AnonDirName\s\+.*|AnonDirName /var/spool/cups-pdf/jobs|' \
        -e 's|^#\?\s*AnonUser\s\+.*|AnonUser root|' \
        -e 's|^#\?\s*DirPrefix\s\+.*|DirPrefix 0|' \
        -e 's|^#\?\s*Label\s\+.*|Label 0|' \
        -e 's|^#\?\s*Grp\s\+.*|Grp lp|' \
        -e 's|^#\?\s*LogType\s\+.*|LogType 7|' \
        /etc/cups/cups-pdf.conf \
    && mkdir -p /var/spool/cups-pdf/jobs /var/spool/cups-pdf/SPOOL /run/cups \
    && chown -R root:lp /var/spool/cups-pdf /run/cups \
    && chmod -R 0775 /var/spool/cups-pdf

COPY webui.py /opt/webui/webui.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 631 8080

VOLUME ["/var/spool/cups-pdf/jobs"]

ENTRYPOINT ["/entrypoint.sh"]
