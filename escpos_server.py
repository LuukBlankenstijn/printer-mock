"""
Tiny TCP sink for raw ESC/POS byte streams.

Real network thermal printers listen on TCP port 9100 ("JetDirect" / RAW)
and accept whatever the client writes until the connection closes. We do
the same: every accepted connection becomes one job, saved as a .bin file
in `save_dir`.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path


def _handle(conn: socket.socket, addr, save_dir: Path,
            max_bytes: int, idle_timeout: float) -> None:
    conn.settimeout(idle_timeout)
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            try:
                data = conn.recv(65536)
            except socket.timeout:
                # Most clients leave the connection open; treat idle as EOJ.
                break
            if not data:
                break
            chunks.append(data)
            total += len(data)
            if total >= max_bytes:
                break
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not chunks:
        return
    raw = b"".join(chunks)
    save_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    ip = addr[0].replace(":", "_") if addr else "unknown"
    name = f"{ts}-{ip}-{total}b.bin"
    # Avoid collision within the same second
    target = save_dir / name
    seq = 1
    while target.exists():
        target = save_dir / f"{ts}-{ip}-{total}b-{seq}.bin"
        seq += 1
    target.write_bytes(raw)


def _serve(host: str, port: int, save_dir: Path,
           max_bytes: int, idle_timeout: float) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(16)
    while True:
        try:
            conn, addr = s.accept()
        except OSError:
            continue
        t = threading.Thread(
            target=_handle,
            args=(conn, addr, save_dir, max_bytes, idle_timeout),
            daemon=True,
        )
        t.start()


def start(save_dir: Path, host: str = "0.0.0.0", port: int = 9100,
          max_bytes: int = 10 * 1024 * 1024,
          idle_timeout: float = 1.5) -> threading.Thread:
    """Spawn the ESC/POS sink server in a background daemon thread."""
    t = threading.Thread(
        target=_serve,
        args=(host, port, save_dir, max_bytes, idle_timeout),
        daemon=True,
        name="escpos-server",
    )
    t.start()
    return t
