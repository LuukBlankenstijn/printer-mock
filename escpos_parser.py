"""
Minimal ESC/POS byte-stream → HTML renderer.

We don't faithfully simulate every thermal-printer quirk. We just want a
readable preview of what a client sent: text (with bold / underline /
double-size), alignment, line feeds, cuts, and raster images.
Unknown commands are best-effort skipped without crashing.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


@dataclass
class Style:
    bold: bool = False
    underline: bool = False
    double_w: bool = False
    double_h: bool = False
    invert: bool = False

    def css(self) -> str:
        parts = []
        if self.bold:
            parts.append("font-weight:700")
        if self.underline:
            parts.append("text-decoration:underline")
        if self.double_w and self.double_h:
            parts.append("font-size:2em;line-height:1")
        elif self.double_w:
            parts.append("letter-spacing:0.5em")
        elif self.double_h:
            parts.append("font-size:2em;line-height:1")
        if self.invert:
            parts.append("background:#111;color:#fdfcf6;padding:0 3px")
        return ";".join(parts)

    def copy(self) -> "Style":
        return Style(self.bold, self.underline, self.double_w, self.double_h, self.invert)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def _raster_to_png_b64(width_bytes: int, height: int, data: bytes) -> str | None:
    """Convert ESC/POS raster (1bpp, MSB-first per byte, row-major) to base64 PNG.

    Black dots are opaque; non-printed pixels are transparent so the paper
    background shows through (like real thermal output)."""
    if not HAS_PIL or width_bytes <= 0 or height <= 0:
        return None
    px_w = width_bytes * 8
    img = Image.new("LA", (px_w, height), (0, 0))  # transparent
    pixels = img.load()
    idx = 0
    for y in range(height):
        for xb in range(width_bytes):
            if idx >= len(data):
                break
            byte = data[idx]
            idx += 1
            for bit in range(8):
                if byte & (0x80 >> bit):
                    pixels[xb * 8 + bit, y] = (0, 255)  # opaque black
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_html(data: bytes) -> str:
    """Return an HTML fragment rendering the given ESC/POS byte stream."""
    style = Style()
    align = "left"
    blocks: list[str] = []
    line_segs: list[tuple[str, Style]] = []
    cur_text = ""

    def flush_text():
        nonlocal cur_text
        if cur_text:
            line_segs.append((cur_text, style.copy()))
            cur_text = ""

    def flush_line(emit_blank: bool = True):
        flush_text()
        if line_segs:
            inner = "".join(
                (f'<span style="{s.css()}">{_esc(t)}</span>' if s.css() else _esc(t))
                for t, s in line_segs
            )
            blocks.append(f'<div class="line align-{align}">{inner}</div>')
            line_segs.clear()
        elif emit_blank:
            blocks.append(f'<div class="line align-{align}">&nbsp;</div>')

    def add_block(html: str):
        flush_line(emit_blank=False)
        blocks.append(html)

    i = 0
    n = len(data)
    while i < n:
        b = data[i]

        # --- ESC ... ---
        if b == 0x1B and i + 1 < n:
            cmd = data[i + 1]
            i += 2
            if cmd == 0x40:  # ESC @ : initialize
                style = Style()
                align = "left"
            elif cmd == 0x21 and i < n:  # ESC ! n : print mode bits
                flush_text()
                v = data[i]; i += 1
                style.bold = bool(v & 0x08)
                style.double_h = bool(v & 0x10)
                style.double_w = bool(v & 0x20)
                style.underline = bool(v & 0x80)
            elif cmd == 0x45 and i < n:  # ESC E n : bold
                flush_text()
                style.bold = data[i] != 0; i += 1
            elif cmd == 0x47 and i < n:  # ESC G n : double-strike (treat as bold)
                flush_text()
                style.bold = data[i] != 0; i += 1
            elif cmd == 0x2D and i < n:  # ESC - n : underline
                flush_text()
                style.underline = data[i] != 0; i += 1
            elif cmd == 0x61 and i < n:  # ESC a n : justification
                flush_text()
                v = data[i]; i += 1
                align = {0: "left", 1: "center", 2: "right",
                         48: "left", 49: "center", 50: "right"}.get(v, "left")
            elif cmd == 0x64 and i < n:  # ESC d n : feed n lines
                k = data[i]; i += 1
                for _ in range(max(k, 1)):
                    flush_line()
            elif cmd == 0x4A and i < n:  # ESC J n : feed n motion units
                i += 1
                flush_line()
            elif cmd == 0x2A and i + 2 < n:  # ESC * m nL nH data
                m = data[i]; nl = data[i + 1]; nh = data[i + 2]; i += 3
                dots = nl + nh * 256
                # 0,1 = 8-dot (1 byte/col); 32,33 = 24-dot (3 bytes/col)
                bytes_per_col = 3 if m in (32, 33) else 1
                i += dots * bytes_per_col
                add_block(f'<div class="note">[bit image, {dots} dots wide]</div>')
            elif cmd == 0x74 and i < n:  # ESC t n : code table
                i += 1
            elif cmd == 0x52 and i < n:  # ESC R n : international charset
                i += 1
            elif cmd == 0x33 and i < n:  # ESC 3 n : set line spacing
                i += 1
            elif cmd == 0x32:  # ESC 2 : default line spacing
                pass
            elif cmd == 0x70 and i + 2 < n:  # ESC p m t1 t2 : drawer pulse
                i += 3
                add_block('<div class="note">[cash drawer pulse]</div>')
            elif cmd == 0x4D and i < n:  # ESC M n : font
                i += 1
            elif cmd == 0x7B and i < n:  # ESC { n : upside-down
                i += 1
            elif cmd == 0x44:  # ESC D : horizontal tab stops (NUL terminated)
                while i < n and data[i] != 0:
                    i += 1
                if i < n:
                    i += 1
            elif cmd == 0x42 and i < n:  # ESC B n : feedback / beeper on some printers
                i += 1
            elif cmd == 0x3F and i < n:  # ESC ? n : cancel user-defined char
                i += 1
            else:
                # Unknown ESC command — best-effort consume 1 byte arg
                if i < n:
                    i += 1

        # --- GS ... ---
        elif b == 0x1D and i + 1 < n:
            cmd = data[i + 1]
            i += 2
            if cmd == 0x21 and i < n:  # GS ! n : character size
                flush_text()
                v = data[i]; i += 1
                style.double_w = (v >> 4) > 0
                style.double_h = (v & 0x0F) > 0
            elif cmd == 0x42 and i < n:  # GS B n : reverse video
                flush_text()
                style.invert = data[i] != 0; i += 1
            elif cmd == 0x56 and i < n:  # GS V : cut paper
                m = data[i]; i += 1
                if m in (65, 66) and i < n:  # GS V 65 n  / GS V 66 n
                    i += 1
                add_block('<hr class="cut" title="paper cut">')
            elif cmd == 0x76 and i < n and data[i] == 0x30 and i + 5 < n:
                # GS v 0 m xL xH yL yH d1..dk : raster bit image
                i += 1  # consume '0'
                m = data[i]; xl = data[i + 1]; xh = data[i + 2]
                yl = data[i + 3]; yh = data[i + 4]
                i += 5
                w_bytes = xl + xh * 256
                height = yl + yh * 256
                size = w_bytes * height
                payload = data[i:i + size]; i += size
                b64 = _raster_to_png_b64(w_bytes, height, payload)
                if b64:
                    sx = 2 if (m & 1) else 1
                    sy = 2 if (m & 2) else 1
                    px_w = w_bytes * 8 * sx
                    px_h = height * sy
                    add_block(
                        f'<div class="img-wrap align-{align}">'
                        f'<img alt="raster" '
                        f'src="data:image/png;base64,{b64}" '
                        f'style="image-rendering:pixelated;width:{px_w}px;height:{px_h}px">'
                        f'</div>'
                    )
                else:
                    add_block(
                        f'<div class="note">[raster image '
                        f'{w_bytes * 8}×{height}px; install Pillow for preview]</div>'
                    )
            elif cmd == 0x28 and i + 2 < n:
                # GS ( fn pL pH ...payload(pL+pH*256 bytes)
                fn = data[i]; pl = data[i + 1]; ph = data[i + 2]
                i += 3
                plen = pl + ph * 256
                payload = data[i:i + plen]; i += plen
                if fn == 0x6B and len(payload) >= 3:  # GS ( k : 2D codes
                    cn = payload[0]
                    sub = payload[1] if len(payload) > 1 else 0
                    if cn == 49 and sub == 0x51:  # QR print
                        add_block('<div class="note">[QR code]</div>')
                    elif cn == 49 and sub == 0x50:  # QR store data
                        try:
                            qrdata = payload[3:].decode("utf-8", "replace")
                            add_block(f'<div class="note">[QR data: {_esc(qrdata)}]</div>')
                        except Exception:
                            add_block('<div class="note">[QR data]</div>')
            elif cmd == 0x68 and i < n:  # GS h n : barcode height
                i += 1
            elif cmd == 0x48 and i < n:  # GS H n : HRI position
                i += 1
            elif cmd == 0x66 and i < n:  # GS f n : HRI font
                i += 1
            elif cmd == 0x77 and i < n:  # GS w n : barcode width
                i += 1
            elif cmd == 0x6B and i < n:  # GS k m ... : barcode
                m = data[i]; i += 1
                if m <= 6:
                    start = i
                    while i < n and data[i] != 0:
                        i += 1
                    bdata = data[start:i]
                    if i < n:
                        i += 1
                    add_block(
                        f'<div class="note">[barcode (type {m}): '
                        f'{_esc(bdata.decode("ascii", "replace"))}]</div>'
                    )
                elif i < n:
                    length = data[i]; i += 1
                    bdata = data[i:i + length]; i += length
                    add_block(
                        f'<div class="note">[barcode (type {m}): '
                        f'{_esc(bdata.decode("ascii", "replace"))}]</div>'
                    )
            elif cmd == 0x4C and i + 1 < n:  # GS L : left margin
                i += 2
            elif cmd == 0x50 and i + 1 < n:  # GS P : motion units
                i += 2
            elif cmd == 0x57 and i + 1 < n:  # GS W : print area width
                i += 2
            elif cmd == 0x61 and i < n:  # GS a n : automatic status back
                i += 1
            elif cmd == 0x72 and i < n:  # GS r n : transmit status
                i += 1
            else:
                if i < n:
                    i += 1

        elif b == 0x0A:  # LF
            flush_line(); i += 1
        elif b == 0x0D:  # CR — most ESC/POS printers ignore
            i += 1
        elif b == 0x0C:  # FF — page eject; treat as a break
            add_block('<hr class="cut" title="form feed">')
            i += 1
        elif b == 0x09:  # HT — tab
            cur_text += "    "; i += 1
        elif b < 0x20:  # other control bytes — skip
            i += 1
        else:
            cur_text += bytes([b]).decode("cp437", "replace")
            i += 1

    flush_line(emit_blank=False)
    return "\n".join(blocks)
