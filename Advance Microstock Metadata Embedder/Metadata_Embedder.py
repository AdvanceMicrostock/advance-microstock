#!/usr/bin/env python3
"""
Advance Microstock PRO - Metadata Embedder (GUI)
Drag & drop your files + CSV (or use Browse), then click Embed Metadata

Requirements: Python 3 (with tkinter), ExifTool (place exiftool.exe next to this file),
              FFmpeg (only needed for WebM)
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk
from xml.sax.saxutils import escape

APP_DIR = Path(__file__).resolve().parent
# exiftool.exe / ffmpeg.exe placed next to this file will be found too
os.environ["PATH"] = str(APP_DIR) + os.pathsep + os.environ.get("PATH", "")

EXIF_EXT = {".jpg", ".jpeg", ".png", ".webp", ".eps", ".ai", ".mp4", ".mov"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- core logic
def kw_list(s):
    """Splits keywords, removes duplicates (case-insensitive), keeps the order."""
    out, seen = [], set()
    for k in re.split(r"[,;]", s or ""):
        k = k.strip().replace("|", " ")
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out


SEP = "|"
RATING_PERCENT = {"1": "1", "2": "25", "3": "50", "4": "75", "5": "99"}


def exif_subject_count(path):
    """Returns how many keywords (XMP-dc:Subject) the file currently has."""
    try:
        r = subprocess.run(["exiftool", "-j", "-XMP-dc:Subject", str(path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW)
    except FileNotFoundError:
        return None
    try:
        v = json.loads(r.stdout)[0].get("Subject")
    except Exception:
        return None
    if v is None:
        return 0
    return len(v) if isinstance(v, list) else 1


def _run_exiftool(args, strict=True):
    try:
        r = subprocess.run(["exiftool", "-overwrite_original", "-charset", "utf8"] + args,
                           capture_output=True, text=True, creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise RuntimeError("ExifTool not found (place exiftool.exe next to the app)")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "exiftool error")
    if not strict:
        return r
    # "0 files updated" + warning mane kichu likha jayni (jemon PostScript-AI file)
    m = re.search(r"(\d+) image files updated", r.stdout)
    if m and int(m.group(1)) == 0 and re.search(r"warning|error", r.stderr, re.I):
        raise RuntimeError(r.stderr.strip().splitlines()[0])
    return r


def write_exiftool(path, row):
    """1) Wipes all existing metadata (-all=)  2) Writes the CSV data.
    If a CSV field is empty, that field will be empty in the file."""
    title = row.get("title", "").strip()
    desc = row.get("description", "").strip()
    kws = kw_list(row.get("keywords", ""))
    author = row.get("author", "").strip()
    copyright_ = row.get("copyright", "").strip()
    rating = row.get("rating", "").strip()
    ext = path.suffix.lower()
    joined = SEP.join(kws)

    # ---- Step 1: puro metadata remove (color profile/orientation rekhe)
    full_wipe = ext in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}
    if full_wipe:
        wipe = ["-all="]
        if ext in {".jpg", ".jpeg", ".png", ".webp"}:
            wipe += ["-tagsFromFile", "@", "-ICC_Profile"]
            if ext != ".png":
                wipe += ["-Orientation"]
        _run_exiftool(wipe + [str(path)], strict=False)
    elif ext == ".ai":
        # .ai needs its own technical XMP, so only the description fields are wiped
        _run_exiftool(["-XMP-dc:all=", str(path)], strict=False)

    # ---- Step 2: CSV-r notun data
    tags = {
        "XMP-dc:Title": title,
        "XMP-dc:Description": desc,
        "XMP-dc:Subject": joined,          # "=" replaces the whole list
        "XMP-dc:Creator": author,
        "XMP-dc:Rights": copyright_,
        "XMP-xmp:Rating": rating,
    }
    if ext in {".jpg", ".jpeg"}:
        tags.update({
            "EXIF:Rating": rating, "EXIF:RatingPercent": RATING_PERCENT.get(rating, ""),
            "IPTC:ObjectName": title, "EXIF:XPTitle": title,
            "IPTC:Caption-Abstract": desc, "EXIF:ImageDescription": desc,
            "IPTC:Keywords": joined, "EXIF:XPKeywords": ";".join(kws),
            "IPTC:By-line": author, "IPTC:CopyrightNotice": copyright_,
            "EXIF:Artist": author, "EXIF:Copyright": copyright_,
        })
    if full_wipe:
        tags = {t: v for t, v in tags.items() if v}     # nothing left to clear; empty values are not written
    args = ["-sep", SEP] + [f"-{t}={v}" for t, v in tags.items()]
    if tags:
        _run_exiftool(args + [str(path)])

    # After writing: verify the keyword count is correct
    n = exif_subject_count(path)
    if n is not None and n != len(kws):
        _run_exiftool(["-XMP-dc:Subject=", str(path)], strict=False)
        if tags:
            _run_exiftool(args + [str(path)])
        n = exif_subject_count(path)
        if n is not None and n != len(kws):
            raise RuntimeError(f"keyword count mismatch (found {n}, expected {len(kws)})")


def write_eps_xmp(path, row):
    """Edits the XMP packet inside the EPS directly (no Illustrator/ExifTool needed).
    The file byte-length stays identical, so EPS preview/offsets are not broken."""
    data = path.read_bytes()
    a = data.find(b"<?xpacket begin")
    b = data.find(b"<?xpacket end", a)
    if a < 0 or b < 0:
        raise LookupError("No XMP packet in EPS")
    e = data.find(b"?>", b) + 2
    packet = data[a:e].decode("utf-8")

    title = escape(row.get("title", "").strip())
    desc = escape(row.get("description", "").strip())
    kws = [escape(k) for k in kw_list(row.get("keywords", ""))]
    author = escape(row.get("author", "").strip())
    rights = escape(row.get("copyright", "").strip())
    rating = escape(row.get("rating", "").strip())

    def drop_ns(p, prefix, skip=()):
        # removes both <prefix:Name .../> and <prefix:Name ...>...</prefix:Name>
        skip_re = "".join("(?!%s\\b)" % x for x in skip)
        p = re.sub(r"<%s:%s(\w+)\b[^>]*/>[ \t]*\r?\n?" % (prefix, skip_re), "", p)
        return re.sub(r"<%s:%s(\w+)\b[^>]*>.*?</%s:\1>[ \t]*\r?\n?" % (prefix, skip_re, prefix),
                      "", p, flags=re.S)

    # Remove all old descriptive metadata (Illustrator technical XMP is kept)
    packet = drop_ns(packet, "dc", skip=("format",))
    packet = re.sub(r"<xmp:Rating\b[^>]*/>[ \t]*\r?\n?", "", packet)
    packet = re.sub(r"<xmp:Rating\b[^>]*>.*?</xmp:Rating>[ \t]*\r?\n?", "", packet, flags=re.S)
    for pre in ("photoshop", "Iptc4xmpCore", "Iptc4xmpExt", "xmpRights", "lr", "plus", "pdf"):
        packet = drop_ns(packet, pre)

    new = ""
    if title:
        new += '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">%s</rdf:li></rdf:Alt></dc:title>\n' % title
    if desc:
        new += '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">%s</rdf:li></rdf:Alt></dc:description>\n' % desc
    if kws:
        new += "<dc:subject><rdf:Bag>%s</rdf:Bag></dc:subject>\n" % "".join(
            "<rdf:li>%s</rdf:li>" % k for k in kws)
    if author:
        new += "<dc:creator><rdf:Seq><rdf:li>%s</rdf:li></rdf:Seq></dc:creator>\n" % author
    if rights:
        new += '<dc:rights><rdf:Alt><rdf:li xml:lang="x-default">%s</rdf:li></rdf:Alt></dc:rights>\n' % rights
    if rating:
        new += "<xmp:Rating>%s</xmp:Rating>\n" % rating

    m = re.search(r"<rdf:Description\b[^>]*>", packet)
    if not m:
        raise RuntimeError("rdf:Description not found in XMP")
    tag = m.group(0)
    if "xmlns:dc=" not in tag:
        tag = tag[:-1] + ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
    if "xmlns:xmp=" not in tag:
        tag = tag[:-1] + ' xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
    packet = packet[:m.start()] + tag + packet[m.end():]
    close = packet.find("</rdf:Description>")
    if close < 0:
        raise RuntimeError("</rdf:Description> not found in XMP")
    packet = packet[:close] + new + packet[close:]

    # Keep the packet length the same (shrink from trailing padding)
    old_len = e - a
    endtag = b'<?xpacket end="w"?>'
    pk = packet.encode("utf-8")
    body = pk[: pk.rfind(b"<?xpacket end")].rstrip()
    need = old_len - len(body) - len(endtag)
    if need < 2:
        raise RuntimeError("Not enough room in XMP packet (metadata too large)")
    pk = body + b"\n" + b" " * (need - 1) + endtag
    assert len(pk) == old_len
    path.write_bytes(data[:a] + pk + data[e:])


def write_svg(path, row):
    title = escape(row.get("title", "").strip())
    desc = escape(row.get("description", "").strip())
    kws = [escape(k) for k in kw_list(row.get("keywords", ""))]
    author = escape(row.get("author", "").strip())
    rights = escape(row.get("copyright", "").strip())
    rating = escape(row.get("rating", "").strip())

    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<metadata\b.*?</metadata>", "", text, flags=re.S)
    text = re.sub(r"<title\b[^>]*>.*?</title>", "", text, count=1, flags=re.S)
    text = re.sub(r"<desc\b[^>]*>.*?</desc>", "", text, count=1, flags=re.S)

    m = re.search(r"<svg\b[^>]*?(/?)>", text)
    if not m or m.group(1) == "/":
        raise ValueError("valid <svg> root tag not found")

    subject = "".join(f"<rdf:li>{k}</rdf:li>" for k in kws)
    block = f"\n<title>{title}</title>\n<desc>{desc}</desc>\n"
    block += (
        '<metadata><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        '<rdf:Description rdf:about="">'
        f"<dc:title>{title}</dc:title><dc:description>{desc}</dc:description>"
        f"<dc:subject><rdf:Bag>{subject}</rdf:Bag></dc:subject>"
        + (f"<dc:creator>{author}</dc:creator>" if author else "")
        + (f"<dc:rights>{rights}</dc:rights>" if rights else "")
        + (f"<xmp:Rating>{rating}</xmp:Rating>" if rating else "")
        + "</rdf:Description></rdf:RDF></metadata>\n"
    )
    text = text[: m.end()] + block + text[m.end():]
    path.write_text(text, encoding="utf-8")


def write_webm(path, row):
    tmp = path.with_name(path.stem + "_tmp.webm")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-map", "0", "-c", "copy",
        "-map_metadata", "-1", "-map_chapters", "-1",   # remove all old metadata
        "-metadata", f"title={row.get('title', '')}",
        "-metadata", f"comment={row.get('description', '')}",
        "-metadata", f"description={row.get('description', '')}",
        "-metadata", f"keywords={', '.join(kw_list(row.get('keywords', '')))}",
        "-metadata", f"artist={row.get('author', '')}",
        "-metadata", f"copyright={row.get('copyright', '')}",
        "-metadata", f"rating={row.get('rating', '')}",
        str(tmp),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise RuntimeError("FFmpeg not found (install FFmpeg for WebM files)")
    if r.returncode == 0:
        tmp.replace(path)
    else:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(r.stderr.strip() or "ffmpeg error")


def process_file(path, row):
    ext = path.suffix.lower()
    if ext == ".svg":
        write_svg(path, row)
    elif ext == ".webm":
        write_webm(path, row)
    elif ext == ".eps":
        try:
            write_eps_xmp(path, row)
        except LookupError:
            write_exiftool(path, row)   # if there is no XMP packet, try ExifTool
    elif ext in EXIF_EXT:
        write_exiftool(path, row)
    else:
        return False
    return True


# ------------------------------------------------------- notification helpers
def fmt_time(sec):
    sec = int(max(0, sec))
    if sec < 60:
        return f"{sec}s"
    m, s_ = divmod(sec, 60)
    if m < 60:
        return f"{m}m {s_:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _settings_paths():
    paths = [APP_DIR / "settings.json"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "MetadataEmbedder" / "settings.json")
    return paths


def load_settings():
    for path in _settings_paths():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def save_settings(data):
    for path in _settings_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return
        except Exception:
            continue


def speak_text(text, gender="Female"):
    """Reads text aloud with the Windows voice (gender = 'Female' or 'Male')."""
    if sys.platform != "win32":
        return
    if gender == "Off":
        return
    gender = "Male" if gender == "Male" else "Female"
    text = text.replace("'", " ")
    ps = ("Add-Type -AssemblyName System.Speech; "
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"try {{ $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::{gender}) }} catch {{}}; "
          f"$s.Speak('{text}')")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                        "-Command", ps], creationflags=NO_WINDOW, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        pass


def speak_result(ok, fail, missing, gender="Female"):
    """1) plays the short tune (happy = all fine, low = something failed)
    2) then the chosen voice reads the result, e.g.
       'Boss, embedding finished. All 145 files are done.'"""
    if sys.platform != "win32":
        return
    try:
        import winsound
        tune = ((784, 110), (988, 110), (1175, 220)) if not fail else ((440, 230), (330, 230), (262, 400))
        for freq, ms in tune:
            winsound.Beep(freq, ms)
    except Exception:
        pass
    if gender == "Off":         # voice turned off: only the tune plays
        return
    if fail or missing:
        speak_text("Boss, embedding finished. Some files need attention.", gender)
    else:
        speak_text(f"Boss, embedding finished. All {int(ok)} files are done.", gender)


def flash_taskbar(win, stop=False):
    """Makes the taskbar icon blink until the window is brought to the front (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                        ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                        ("dwTimeout", wintypes.DWORD)]

        user32 = ctypes.WinDLL("user32")
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
        inner = win.winfo_id()
        hwnd = user32.GetParent(inner) or inner
        # FLASHW_STOP = 0 | FLASHW_TRAY (2) + FLASHW_TIMERNOFG (0xC): blink until the app comes to the front
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0 if stop else 0x0E, 0, 0)
        user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        log_error()


def open_path(p):
    """Opens a file or a folder with the default app / Explorer."""
    try:
        if sys.platform == "win32":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception:
        log_error()


# ---------------------------------------------------------------------- GUI
# Theme: Advance Microstock PRO (dark navy + gold, left sidebar)
BG = "#070b13"
SIDEBAR = "#0a101c"
PANEL = "#0e1423"
TOPBAR = "#0c1220"
DZ = "#0b1220"
LINE = "#252f4b"
LINE2 = "#35446b"
LINEGOLD = "#3a3120"
INPUT = "#0b1220"
TEXT = "#f6f3ec"
SOFT = "#e3e8f1"
MUTED = "#aab4c9"
GOLD = "#f0cf8e"
GOLD2 = "#d6a85a"
OK = "#3ddc9c"
BAD = "#ff7a93"
WARN = "#ffd27a"
FONT = "Segoe UI"
MONO = "Consolas"
SCALE = 1.0
HEADER_H = 72
SUPPORTED = [".jpg", ".jpeg", ".png", ".webp", ".eps", ".ai", ".svg", ".mp4", ".webm", ".mov"]

LOGO48 = """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\
QmCC"""
LOGO64 = """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"""



def log_error():
    """Write the current error to error_log.txt next to the app (pythonw hides errors)."""
    try:
        import traceback
        with open(APP_DIR / "error_log.txt", "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass


def px(n):
    return max(1, int(round(n * SCALE)))


def rrect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class Card(tk.Frame):
    """Rounded panel. Put widgets in .body. fill=True makes it take all remaining space."""

    def __init__(self, master, title=None, fill=False, bg=SIDEBAR, pad=12):
        super().__init__(master, bg=bg)
        self.pad = px(pad)
        self.fill = fill
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, height=px(20))
        self.cv.pack(fill="both" if fill else "x", expand=fill)
        self.body = tk.Frame(self.cv, bg=PANEL)
        self.win = self.cv.create_window(self.pad, self.pad, window=self.body, anchor="nw")
        self.cv.bind("<Configure>", self._redraw)
        if not fill:
            self.body.bind("<Configure>", self._redraw)
        if title:
            tk.Label(self.body, text=title.upper(), bg=PANEL, fg=GOLD,
                     font=(FONT, 8, "bold")).pack(anchor="w", pady=(0, px(8)))

    def _redraw(self, _e=None):
        w = self.cv.winfo_width()
        if w < 10:
            return
        if self.fill:
            h = self.cv.winfo_height()
        else:
            h = self.body.winfo_reqheight() + 2 * self.pad
            try:
                if int(float(self.cv.cget("height"))) != h:
                    self.cv.configure(height=h)
            except Exception:
                self.cv.configure(height=h)
        self.cv.delete("bg")
        rrect(self.cv, 1, 1, w - 2, h - 2, px(12), fill=PANEL, outline=LINE, width=1, tags="bg")
        self.cv.tag_lower("bg")
        opts = {"width": max(10, w - 2 * self.pad)}
        if self.fill:
            opts["height"] = max(10, h - 2 * self.pad)
        self.cv.itemconfigure(self.win, **opts)


class DropZone(tk.Frame):
    """Dashed drag & drop area. Put widgets in .body (centered)."""

    def __init__(self, master, bg=BG, height=226):
        super().__init__(master, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, height=px(height))
        self.cv.pack(fill="x")
        self.body = tk.Frame(self.cv, bg=DZ)
        self.win = self.cv.create_window(0, 0, window=self.body, anchor="center")
        self.cv.bind("<Configure>", self._redraw)

    def _redraw(self, _e=None):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        if w < 10:
            return
        self.cv.delete("bg")
        rrect(self.cv, 2, 2, w - 3, h - 3, px(14), fill=DZ, outline=LINE2, width=1,
              dash=(5, 4), tags="bg")
        self.cv.tag_lower("bg")
        self.cv.coords(self.win, w / 2, h / 2)


class Btn(tk.Canvas):
    """Rounded button. kind = 'primary' (gold) or 'secondary'."""

    def __init__(self, master, text, command, kind="secondary", height=34, width=None,
                 font=None, bg=PANEL):
        kw = {"width": width} if width else {}
        super().__init__(master, height=px(height), bg=bg, highlightthickness=0,
                         cursor="hand2", **kw)
        self.text, self.command, self.kind = text, command, kind
        self.hover, self.enabled = False, True
        self.font = font or (FONT, 10, "bold")
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._click)

    def _set_hover(self, v):
        self.hover = v
        self.draw()

    def _click(self, _e=None):
        if self.enabled and self.command:
            self.command()

    def set_text(self, text):
        self.text = text
        self.draw()

    def set_enabled(self, v):
        self.enabled = v
        self.configure(cursor="hand2" if v else "arrow")
        self.draw()

    def draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        self.delete("all")
        if not self.enabled:
            fill, outline, fg = "#161d2e", LINE, MUTED
        elif self.kind == "primary":
            fill, outline, fg = (GOLD if self.hover else GOLD2), "", "#1a1204"
        else:
            fill = "#1a2538" if self.hover else "#141c2c"
            outline, fg = (GOLD2 if self.hover else LINE2), SOFT
        rrect(self, 1, 1, w - 1, h - 1, px(9), fill=fill, outline=outline, width=1)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font)


class Pill(tk.Canvas):
    """Gol-kona pill (badge / counter)."""

    def __init__(self, master, text, fg, fill, outline, font=None, height=22, bg=TOPBAR):
        self.fg, self.fill, self.outline = fg, fill, outline
        self.font = font or (FONT, 9, "bold")
        self.ph = px(height)
        self.text = text
        self._f = tkfont.Font(font=self.font)
        super().__init__(master, height=self.ph, width=self._width(), bg=bg, highlightthickness=0)
        self.draw()

    def _width(self):
        return int(self._f.measure(self.text)) + px(20)

    def set_text(self, text):
        self.text = text
        self.configure(width=self._width())
        self.draw()

    def draw(self):
        self.delete("all")
        w = self._width()
        rrect(self, 1, 1, w - 1, self.ph - 1, self.ph // 2, fill=self.fill, outline=self.outline, width=1)
        self.create_text(w / 2, self.ph / 2, text=self.text, fill=self.fg, font=self.font)


class Toggle(tk.Canvas):
    """Modern ON/OFF switch bound to a BooleanVar."""

    def __init__(self, master, var, bg=PANEL):
        self.tw, self.th = px(36), px(20)      # same size as the HTML tool's switch
        super().__init__(master, width=self.tw, height=self.th, bg=bg,
                         highlightthickness=0, cursor="hand2")
        self.var = var
        self.bind("<Button-1>", lambda e: self.var.set(not self.var.get()))
        var.trace_add("write", lambda *a: self.draw())
        self.draw()

    @staticmethod
    def _mix(c1, c2, t):
        a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
        return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def draw(self):
        self.delete("all")
        on = self.var.get()
        w, h = self.tw, self.th
        if on:
            # same look as the HTML tool: gold gradient (#f0cf8e -> #d6a85a), dark knob on the right
            self.create_oval(0, 0, h, h, fill="#f0cf8e", outline="#f0cf8e")
            self.create_oval(w - h, 0, w, h, fill="#d6a85a", outline="#d6a85a")
            x0, x1 = int(h / 2), int(w - h / 2)
            for x in range(x0, x1 + 1):
                col = self._mix("#f0cf8e", "#d6a85a", (x - h / 2) / max(1, w - h))
                self.create_line(x, 0, x, h, fill=col)
            knob = "#1a1204"
        else:
            # off: flat #273248 track, white knob on the left
            col = "#273248"
            self.create_oval(0, 0, h, h, fill=col, outline=col)
            self.create_oval(w - h, 0, w, h, fill=col, outline=col)
            self.create_rectangle(h / 2, 0, w - h / 2, h, fill=col, outline=col)
            knob = "#ffffff"
        d = px(14)
        pad = (h - d) / 2
        x = w - pad - d if on else pad
        self.create_oval(x, pad, x + d, pad + d, fill=knob, outline="")


PREFIX = {"[OK]": ("✔", "ok"), "[FAIL]": ("✖", "err"), "[MISSING]": ("⚠", "warn"),
          "[SKIP]": ("↷", "warn"), "[PAUSED]": ("⏸", "warn"), "[RESUMED]": ("▶", "ok"),
          "[STOPPED]": ("⏹", "warn"), "[UNTOUCHED]": ("●", "warn")}


class App(tk.Tk):
    def __init__(self):
        global SCALE
        super().__init__()
        try:
            SCALE = max(1.0, float(self.winfo_fpixels("1i")) / 96.0)
        except Exception:
            SCALE = 1.0
        self.title("Advance Microstock PRO  -  Metadata Embedder")
        self.configure(bg=BG)
        self.geometry(f"{px(1040)}x{px(700)}")
        self.minsize(px(960), px(660))

        self.sources = []          # file ba folder Path-er list
        self.csv_path = None
        self.files_text = tk.StringVar()
        self.csv_text = tk.StringVar()
        cfg = load_settings()      # options are remembered between runs
        self.sub_var = tk.BooleanVar(value=bool(cfg.get("subfolders", True)))
        self.backup_var = tk.BooleanVar(value=bool(cfg.get("backup", True)))
        self.rating_var = tk.BooleanVar(value=bool(cfg.get("rating", True)))
        self.notify_var = tk.BooleanVar(value=bool(cfg.get("notify", True)))   # popup + sound + blink
        self.voice = cfg.get("voice") if cfg.get("voice") in ("Off", "Female", "Male") else "Female"
        for v in (self.sub_var, self.backup_var, self.rating_var, self.notify_var):
            v.trace_add("write", lambda *a: self.save_options())
        self.running = False
        self.paused = False
        self.stopping = False
        self.dnd_ok = False
        self.frac = 0.0
        self.run_lines = []        # saved to the .txt log at the end of a run
        self.run_started = 0.0
        self.last_folder = None
        self.popup = None

        self.logo = tk.PhotoImage(data=LOGO64 if SCALE >= 1.4 else LOGO48)
        self.icon = tk.PhotoImage(data=LOGO64)
        try:
            self.iconphoto(True, self.icon)
        except Exception:
            pass

        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Dark.Vertical.TScrollbar", background=LINE2, troughcolor="#090f1a",
                     bordercolor="#090f1a", lightcolor=LINE2, darkcolor=LINE2,
                     arrowcolor=MUTED, gripcount=0)
        st.map("Dark.Vertical.TScrollbar", background=[("active", GOLD2)])

        self.build_sidebar()
        self.build_main()
        self.refresh_selection()
        self.after(250, self.enable_drop)

    # ------------------------------------------------------------ sidebar
    def build_sidebar(self):
        side = tk.Frame(self, bg=SIDEBAR, width=px(318))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self, bg=LINEGOLD, width=1).pack(side="left", fill="y")

        # brand (topbar-er shathe ek-i uchchota)
        head = tk.Frame(side, bg=TOPBAR, height=px(HEADER_H))
        head.pack(fill="x")
        head.pack_propagate(False)
        brand = tk.Frame(head, bg=TOPBAR)
        brand.place(x=px(16), rely=0.5, anchor="w")
        tk.Label(brand, image=self.logo, bg=TOPBAR).pack(side="left")
        txt = tk.Frame(brand, bg=TOPBAR)
        txt.pack(side="left", padx=px(10))
        line = tk.Frame(txt, bg=TOPBAR)
        line.pack(anchor="w")
        tk.Label(line, text="Advance ", bg=TOPBAR, fg=TEXT, font=(FONT, 12, "bold")).pack(side="left")
        tk.Label(line, text="Microstock", bg=TOPBAR, fg=GOLD, font=(FONT, 12, "bold")).pack(side="left")
        Pill(line, "PRO", GOLD, "#1f1a0f", GOLD2, font=(FONT, 7, "bold"), height=16, bg=TOPBAR
             ).pack(side="left", padx=(px(6), 0))
        tk.Label(txt, text="Metadata Embedder", bg=TOPBAR, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        tk.Frame(side, bg=LINEGOLD, height=1).pack(fill="x")

        # start button (niche)
        bottom = tk.Frame(side, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=px(12), pady=px(12))
        self.sel_label = tk.Label(bottom, text="", bg=SIDEBAR, fg=MUTED, font=(FONT, 9), anchor="w")
        self.sel_label.pack(fill="x", pady=(0, px(8)))
        self.btnrow = tk.Frame(bottom, bg=SIDEBAR)          # Embed + Clear side by side
        self.btnrow.pack(fill="x")
        self.clear_btn = Btn(self.btnrow, "✕  Clear", self.clear_selection, height=44, width=px(88),
                             font=(FONT, 10, "bold"), bg=SIDEBAR)
        self.clear_btn.pack(side="right", padx=(px(8), 0))
        self.btn = Btn(self.btnrow, "⚡  Embed Metadata", self.start, kind="primary", height=44,
                       width=px(190), font=(FONT, 11, "bold"), bg=SIDEBAR)
        self.btn.pack(side="left", fill="x", expand=True)
        # shown instead of the Embed button while a run is active
        self.ctrl = tk.Frame(bottom, bg=SIDEBAR)
        self.ctrl.columnconfigure(0, weight=1, uniform="c")
        self.ctrl.columnconfigure(1, weight=1, uniform="c")
        self.pause_btn = Btn(self.ctrl, "⏸  Pause", self.toggle_pause, height=44,
                             font=(FONT, 11, "bold"), bg=SIDEBAR)
        self.pause_btn.grid(row=0, column=0, sticky="ew", padx=(0, px(4)))
        self.stop_btn = Btn(self.ctrl, "⏹  Stop", self.stop_run, height=44,
                            font=(FONT, 11, "bold"), bg=SIDEBAR)
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(px(4), 0))
        self.note = tk.Label(bottom, text="Files not listed in the CSV are never changed", bg=SIDEBAR, fg=MUTED,
                 font=(FONT, 8))
        self.note.pack(pady=(px(6), 0))

        # card 1: files & csv (compact)
        c1 = Card(side, "Files & CSV")
        c1.pack(fill="x", padx=px(12), pady=(px(12), 0))
        Btn(c1.body, "Browse Files + CSV", self.pick_files, kind="primary", height=34,
            font=(FONT, 10, "bold"), bg=PANEL).pack(fill="x", pady=(0, px(10)))
        self.path_field(c1.body, "Files / Folder", self.files_text, "Folder", self.pick_folder
                        ).pack(fill="x", pady=(0, px(8)))
        self.path_field(c1.body, "CSV File", self.csv_text, "Browse", self.pick_csv).pack(fill="x")

        # card 2: options (compact)
        c2 = Card(side, "Options")
        c2.pack(fill="x", padx=px(12), pady=(px(10), 0))
        self.switch_row(c2.body, "Include subfolders", self.sub_var, True)
        self.switch_row(c2.body, "Keep a backup of originals", self.backup_var)
        self.switch_row(c2.body, "Set 5 ★ rating on all files", self.rating_var)
        tk.Frame(c2.body, bg=LINE, height=1).pack(fill="x")
        nrow = tk.Frame(c2.body, bg=PANEL)
        nrow.pack(fill="x", pady=px(5))
        nlbl = tk.Label(nrow, text="Notify when finished", bg=PANEL, fg=SOFT, font=(FONT, 9),
                        cursor="hand2")
        nlbl.pack(side="left")
        nlbl.bind("<Button-1>", lambda e: self.notify_var.set(not self.notify_var.get()))
        Toggle(nrow, self.notify_var).pack(side="right")
        self.voice_btn = Btn(nrow, self.voice_text(), self.cycle_voice, height=22, width=px(84),
                             font=(FONT, 8, "bold"), bg=PANEL)
        self.voice_btn.pack(side="right", padx=(0, px(8)))

    def path_field(self, parent, label, var, btn_text, command):
        box = tk.Frame(parent, bg=PANEL)
        tk.Label(box, text=label, bg=PANEL, fg=SOFT, font=(FONT, 9, "bold")).pack(anchor="w")
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", pady=(px(4), 0))
        row.columnconfigure(0, weight=1)
        ent = tk.Entry(row, textvariable=var, bg=INPUT, fg=TEXT, insertbackground=GOLD,
                       readonlybackground=INPUT, state="readonly", relief="flat",
                       font=(FONT, 9), highlightthickness=1,
                       highlightbackground=LINE2, highlightcolor=GOLD)
        ent.grid(row=0, column=0, sticky="ew", ipady=px(4))
        Btn(row, btn_text, command, height=28, width=px(66), font=(FONT, 9, "bold")
            ).grid(row=0, column=1, padx=(px(6), 0))
        return box

    def switch_row(self, parent, title, var, first=False):
        if not first:
            tk.Frame(parent, bg=LINE, height=1).pack(fill="x")
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=px(5))
        lbl = tk.Label(row, text=title, bg=PANEL, fg=SOFT, font=(FONT, 9), cursor="hand2")
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e: var.set(not var.get()))
        Toggle(row, var).pack(side="right")

    # --------------------------------------------------------------- main
    def build_main(self):
        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        top = tk.Frame(main, bg=TOPBAR, height=px(HEADER_H))
        top.pack(fill="x")
        top.pack_propagate(False)
        left = tk.Frame(top, bg=TOPBAR)
        left.place(x=px(18), rely=0.5, anchor="w")
        tk.Label(left, text="Embed Workspace", bg=TOPBAR, fg=TEXT, font=(FONT, 13, "bold")).pack(anchor="w")
        tk.Label(left, text="Embed full metadata from your CSV  •  old metadata is replaced with the new",
                 bg=TOPBAR, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        pills = tk.Frame(top, bg=TOPBAR)
        pills.place(relx=1.0, x=-px(18), rely=0.5, anchor="e")
        self.p_total = self.pill(pills, "0 Total", SOFT, "#141c2c", LINE2)
        self.p_ok = self.pill(pills, "0 Success", OK, "#0e2a22", "#1d6b52")
        self.p_miss = self.pill(pills, "0 Missing", WARN, "#2b2410", "#7a6320")
        self.p_fail = self.pill(pills, "0 Failed", BAD, "#2d1219", "#8a3347")
        tk.Frame(main, bg=LINEGOLD, height=1).pack(fill="x")

        body = tk.Frame(main, bg=BG)
        body.pack(fill="both", expand=True, padx=px(18), pady=px(14))

        # drop zone
        dz = DropZone(body, bg=BG)
        dz.pack(fill="x")
        d = dz.body
        self.dz_icon = tk.Label(d, text="⇧", bg="#141c2c", fg=GOLD, font=(FONT, 15, "bold"),
                                width=3, highlightthickness=1, highlightbackground=LINE2)
        self.dz_icon.pack(pady=(0, px(8)))
        self.dz_title = tk.Label(d, text="Drag & Drop your files + CSV here", bg=DZ, fg=TEXT,
                                 font=(FONT, 14, "bold"))
        self.dz_title.pack()
        tk.Label(d, text="or use Browse Files + CSV / Folder in the left panel  •  click here to browse",
                 bg=DZ, fg=MUTED, font=(FONT, 9)).pack(pady=(px(2), px(8)))
        tk.Label(d, text="  •  ".join(e.strip(".").upper() for e in
                 [".jpg", ".png", ".webp", ".eps", ".ai", ".svg", ".mp4", ".mov", ".webm"]),
                 bg=DZ, fg=GOLD, font=(MONO, 10, "bold")).pack(pady=(px(2), px(10)))
        self.sel_hint = tk.Label(d, text="Nothing selected yet", bg=DZ, fg=MUTED, font=(FONT, 9))
        self.sel_hint.pack(pady=(px(4), 0))
        for w in (dz, dz.cv, d, self.dz_icon, self.dz_title):
            w.bind("<Button-1>", lambda e: self.pick_files())

        # progress
        pc = Card(body, bg=BG)
        pc.pack(fill="x", pady=(px(12), 0))
        self.track = tk.Canvas(pc.body, height=px(8), bg=PANEL, highlightthickness=0)
        self.track.pack(fill="x")
        self.track.bind("<Configure>", lambda e: self.draw_bar())
        meta = tk.Frame(pc.body, bg=PANEL)
        meta.pack(fill="x", pady=(px(6), 0))
        self.status = tk.Label(meta, text="Ready  -  select files + CSV, then click Embed Metadata",
                               bg=PANEL, fg=MUTED, font=(FONT, 9), anchor="w")
        self.status.pack(side="left")
        self.pct = tk.Label(meta, text="0%", bg=PANEL, fg=GOLD, font=(FONT, 9, "bold"))
        self.pct.pack(side="right")

        # log card
        lc = Card(body, fill=True, bg=BG)
        lc.pack(fill="both", expand=True, pady=(px(12), 0))
        head = tk.Frame(lc.body, bg=PANEL)
        head.pack(fill="x", pady=(0, px(6)))
        tk.Label(head, text="ACTIVITY LOG", bg=PANEL, fg=GOLD, font=(FONT, 8, "bold")).pack(side="left")
        Btn(head, "Clear", self.clear_log, height=22, width=px(52), font=(FONT, 8, "bold")
            ).pack(side="right")

        wrap = tk.Frame(lc.body, bg=PANEL)
        wrap.pack(fill="both", expand=True)
        self.log = tk.Text(wrap, bg="#090f1a", fg=SOFT, insertbackground=GOLD, relief="flat",
                           font=(MONO, 10), wrap="word", state="disabled", padx=px(10),
                           pady=px(8), highlightthickness=1, highlightbackground=LINE,
                           spacing1=2, spacing3=2, cursor="arrow")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.log.yview,
                           style="Dark.Vertical.TScrollbar")
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        for name, col, bold in (("ok", OK, False), ("err", BAD, False), ("warn", WARN, False),
                                ("info", MUTED, False), ("txt", SOFT, False), ("head", GOLD, True)):
            self.log.tag_configure(name, foreground=col,
                                   font=(MONO, 10, "bold") if bold else (MONO, 10))
        self.placeholder = tk.Label(wrap, text="No activity yet", bg="#090f1a", fg=MUTED,
                                    font=(FONT, 10))
        self.placeholder.place(relx=0.5, rely=0.5, anchor="center")

    def pill(self, parent, text, fg, fill, border):
        p = Pill(parent, text, fg, fill, border, bg=TOPBAR)
        p.pack(side="left", padx=(px(6), 0))
        return p

    # ---------------------------------------------------------- selection
    def add_paths(self, paths):
        """Accepts files, folders and CSV - sorts them out automatically."""
        for p in paths:
            p = Path(p)
            if p.suffix.lower() == ".csv" and p.is_file():
                self.csv_path = p
            elif (p.is_dir() or p.is_file()) and p not in self.sources:
                self.sources.append(p)
        # if the folder has exactly one CSV, use it automatically
        if self.csv_path is None:
            for src in self.sources:
                if src.is_dir():
                    found = sorted(src.glob("*.csv"))
                    if len(found) == 1:
                        self.csv_path = found[0]
                        break
        self.refresh_selection()

    def refresh_selection(self):
        nfiles = sum(1 for s in self.sources if s.is_file())
        nfold = sum(1 for s in self.sources if s.is_dir())
        if not self.sources:
            ftxt = ""
        elif nfiles == 0 and nfold == 1:
            ftxt = str(self.sources[0])
        else:
            ftxt = f"{nfiles} files, {nfold} folders"
        self.files_text.set(ftxt)
        self.csv_text.set(str(self.csv_path) if self.csv_path else "")

        self.clear_btn.set_enabled(bool(self.sources or self.csv_path))
        if self.sources and self.csv_path:
            self.sel_label.config(text="Ready to embed.", fg=OK)
            self.sel_hint.config(text=f"{nfiles} files, {nfold} folders  •  CSV: {self.csv_path.name}", fg=SOFT)
        elif self.sources or self.csv_path:
            need = "a CSV file" if self.sources else "files or a folder"
            self.sel_label.config(text=f"Still needed: {need}.", fg=WARN)
            self.sel_hint.config(text=f"Still needed: {need}", fg=WARN)
        else:
            self.sel_label.config(text="Nothing selected yet.", fg=MUTED)
            self.sel_hint.config(text="Nothing selected yet", fg=MUTED)

    def clear_selection(self):
        if self.running:
            return
        self.sources = []
        self.csv_path = None
        self.refresh_selection()

    def pick_files(self):
        exts = " ".join("*" + e for e in SUPPORTED + [".csv"])
        files = filedialog.askopenfilenames(
            title="Select files + CSV together",
            filetypes=[("Supported files + CSV", exts), ("All files", "*.*")])
        if files:
            self.add_paths(files)

    def pick_folder(self):
        d = filedialog.askdirectory(title="Select the folder that contains your files")
        if d:
            self.add_paths([d])

    def pick_csv(self):
        f = filedialog.askopenfilename(
            title="Select CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if f:
            self.add_paths([f])

    # --------------------------------------------- Windows drag & drop
    def enable_drop(self):
        """Drag & drop files/folders/CSV onto the window (Windows)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import c_void_p, c_uint, c_int, c_size_t, c_ssize_t, c_wchar_p
            user32, shell32, comctl32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.comctl32
            WM_DROPFILES, WM_COPYGLOBALDATA = 0x0233, 0x0049

            SUBCLASSPROC = ctypes.WINFUNCTYPE(c_ssize_t, c_void_p, c_uint, c_size_t, c_ssize_t,
                                              c_size_t, c_size_t)
            comctl32.SetWindowSubclass.argtypes = [c_void_p, SUBCLASSPROC, c_size_t, c_size_t]
            comctl32.SetWindowSubclass.restype = c_int
            comctl32.DefSubclassProc.argtypes = [c_void_p, c_uint, c_size_t, c_ssize_t]
            comctl32.DefSubclassProc.restype = c_ssize_t
            shell32.DragQueryFileW.argtypes = [c_void_p, c_uint, c_wchar_p, c_uint]
            shell32.DragQueryFileW.restype = c_uint
            shell32.DragFinish.argtypes = [c_void_p]
            shell32.DragAcceptFiles.argtypes = [c_void_p, c_int]
            user32.GetParent.argtypes = [c_void_p]
            user32.GetParent.restype = c_void_p
            user32.ChangeWindowMessageFilterEx.argtypes = [c_void_p, c_uint, c_uint, c_void_p]

            def handler(hwnd, msg, wp, lp, uid, ref):
                if msg == WM_DROPFILES:
                    paths = []
                    try:
                        n = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                        for i in range(n):
                            ln = shell32.DragQueryFileW(wp, i, None, 0)
                            buf = ctypes.create_unicode_buffer(ln + 1)
                            shell32.DragQueryFileW(wp, i, buf, ln + 1)
                            paths.append(buf.value)
                    except Exception:
                        log_error()
                    finally:
                        try:
                            shell32.DragFinish(wp)
                        except Exception:
                            pass
                    if paths:
                        try:
                            self.after(50, lambda p=paths: self.add_paths(p))
                        except Exception:
                            log_error()
                    return 0
                return comctl32.DefSubclassProc(hwnd, msg, wp, lp)

            self._subproc = SUBCLASSPROC(handler)      # keep a reference, otherwise it crashes
            inner = self.winfo_id()
            outer = user32.GetParent(inner) or inner
            for h in {inner, outer}:
                comctl32.SetWindowSubclass(h, self._subproc, 1, 0)
                shell32.DragAcceptFiles(h, 1)
                try:   # allow drops even when running as administrator
                    for m in (WM_DROPFILES, WM_COPYGLOBALDATA):
                        user32.ChangeWindowMessageFilterEx(h, m, 1, None)
                except Exception:
                    pass
            self.dnd_ok = True
        except Exception:
            log_error()
            self.dnd_ok = False
        if not self.dnd_ok:
            self.dz_title.config(text="Drag & drop unavailable - use Browse")

    def report_callback_exception(self, exc, val, tb):
        log_error()

    # ------------------------------------------------------------ helpers
    def draw_bar(self):
        w, h = self.track.winfo_width(), self.track.winfo_height()
        if w < 4:
            return
        self.track.delete("all")
        r = h / 2
        self.track.create_oval(0, 0, h, h, fill="#1a2338", outline="#1a2338")
        self.track.create_oval(w - h, 0, w, h, fill="#1a2338", outline="#1a2338")
        self.track.create_rectangle(r, 0, w - r, h, fill="#1a2338", outline="#1a2338")
        fw = int(w * self.frac)
        if fw > h:
            self.track.create_oval(0, 0, h, h, fill=GOLD2, outline=GOLD2)
            self.track.create_oval(fw - h, 0, fw, h, fill=GOLD, outline=GOLD)
            self.track.create_rectangle(r, 0, fw - r, h, fill=GOLD2, outline=GOLD2)
        elif fw > 0:
            self.track.create_oval(0, 0, max(fw, h), h, fill=GOLD2, outline=GOLD2)

    def set_progress(self, i, total, text):
        def _do():
            self.frac = (i / total) if total else 0.0
            self.draw_bar()
            self.pct.config(text=f"{int(self.frac * 100)}%")
            self.status.config(text=text, fg=MUTED)
        self.after(0, _do)

    def set_counts(self, total, ok, missing, fail):
        def _do():
            self.p_total.set_text(f"{total} Total")
            self.p_ok.set_text(f"{ok} Success")
            self.p_miss.set_text(f"{missing} Missing")
            self.p_fail.set_text(f"{fail} Failed")
        self.after(0, _do)

    def flash(self, msg, color=WARN):
        self.status.config(text=msg, fg=color)

    def write(self, msg, tag=None):
        self.run_lines.append(msg)
        def _do():
            self.placeholder.place_forget()
            self.log.config(state="normal")
            m = msg
            while m.startswith("\n"):
                self.log.insert("end", "\n")
                m = m[1:]
            for key, (icon, tg) in PREFIX.items():
                if m.startswith(key):
                    self.log.insert("end", icon + "  ", tg)
                    self.log.insert("end", m[len(key):].strip() + "\n", "txt" if tg == "ok" else tg)
                    break
            else:
                self.log.insert("end", m + "\n", "head" if m.startswith("=====") else (tag or "info"))
            self.log.see("end")
            self.log.config(state="disabled")
        self.after(0, _do)

    def clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.placeholder.place(relx=0.5, rely=0.5, anchor="center")

    # ------------------------------------------------------ finished notification
    def save_options(self):
        save_settings({"subfolders": bool(self.sub_var.get()), "backup": bool(self.backup_var.get()),
                       "rating": bool(self.rating_var.get()), "notify": bool(self.notify_var.get()),
                       "voice": self.voice})

    def voice_text(self):
        return {"Female": "♀  Female", "Male": "♂  Male"}.get(self.voice, "Voice off")

    def cycle_voice(self):
        """Click: Female -> Male -> Off -> Female ..."""
        order = ["Female", "Male", "Off"]
        self.set_voice(order[(order.index(self.voice) + 1) % 3])
        self.voice_btn.set_text(self.voice_text())

    def set_voice(self, key):
        """Voice choice: Off / Female / Male. Remembered, and a short preview is spoken."""
        self.voice = key
        self.save_options()
        if key != "Off":
            threading.Thread(target=speak_text, args=(f"Hello boss, this is the {key.lower()} voice.", key),
                             daemon=True).start()

    def notify_done(self, res):
        """Voice + taskbar blink + result popup (only if 'Notify when finished' is ON)."""
        threading.Thread(target=speak_result,
                         args=(res["ok"], res["fail"], res["missing"], self.voice),
                         daemon=True).start()
        flash_taskbar(self)
        try:
            self.show_result_popup(res)
        except Exception:
            log_error()

    def show_result_popup(self, res):
        if self.popup is not None:
            try:
                self.popup.destroy()
            except Exception:
                pass
        nok, nmiss, nfail = res["ok"], res["missing"], res["fail"]
        if nfail:
            accent, icon, head = BAD, "✖", "Finished with errors"
        elif nmiss:
            accent, icon, head = WARN, "⚠", "Finished - some files are missing"
        else:
            accent, icon, head = OK, "✔", "All done!"

        pop = tk.Toplevel(self)
        self.popup = pop
        pop.title("Embedding finished")
        pop.configure(bg=LINEGOLD)
        pop.minsize(px(470), 0)
        try:
            pop.iconphoto(True, self.icon)
        except Exception:
            pass
        box = tk.Frame(pop, bg=PANEL, padx=px(20), pady=px(18))
        box.pack(fill="both", expand=True, padx=1, pady=1)

        # header
        top = tk.Frame(box, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, text=icon, bg=PANEL, fg=accent, font=(FONT, 26, "bold")
                 ).pack(side="left", padx=(0, px(12)))
        tt = tk.Frame(top, bg=PANEL)
        tt.pack(side="left")
        tk.Label(tt, text=head, bg=PANEL, fg=TEXT, font=(FONT, 13, "bold")).pack(anchor="w")
        tk.Label(tt, text=f"{nok} files embedded  •  took {fmt_time(res['elapsed'])}",
                 bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        # counters
        stats = tk.Frame(box, bg=PANEL)
        stats.pack(fill="x", pady=(px(14), 0))
        for text, fg, fill, line in ((f"{nok} Success", OK, "#0e2a22", "#1d6b52"),
                                     (f"{nmiss} Missing", WARN, "#2b2410", "#7a6320"),
                                     (f"{nfail} Failed", BAD, "#2d1219", "#8a3347")):
            Pill(stats, text, fg, fill, line, font=(FONT, 10, "bold"), height=28, bg=PANEL
                 ).pack(side="left", padx=(0, px(8)))
        if res["untouched"]:
            tk.Label(box, text=f"{res['untouched']} files were not in the CSV and were not changed.",
                     bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(px(8), 0))

        # fail / missing list
        issues = [("✖", "err", f"{n}  -  {why}") for n, why in res["fail_items"]]
        issues += [("⚠", "warn", f"{n}  -  not found in the selected files") for n in res["missing_items"]]
        if issues:
            tk.Label(box, text="NEEDS ATTENTION", bg=PANEL, fg=GOLD, font=(FONT, 8, "bold")
                     ).pack(anchor="w", pady=(px(16), px(6)))
            shown, extra = issues[:300], max(0, len(issues) - 300)
            wrap = tk.Frame(box, bg=PANEL)
            wrap.pack(fill="both", expand=True)
            txt = tk.Text(wrap, width=62, height=min(9, len(shown) + (1 if extra else 0)),
                          bg="#090f1a", fg=SOFT, relief="flat", font=(MONO, 9), wrap="word",
                          padx=px(8), pady=px(6), highlightthickness=1, highlightbackground=LINE,
                          cursor="arrow")
            sb = ttk.Scrollbar(wrap, orient="vertical", command=txt.yview,
                               style="Dark.Vertical.TScrollbar")
            txt.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            txt.pack(side="left", fill="both", expand=True)
            txt.tag_configure("err", foreground=BAD)
            txt.tag_configure("warn", foreground=WARN)
            txt.tag_configure("info", foreground=MUTED)
            for ic, tg, line in shown:
                txt.insert("end", f"{ic}  {line}\n", tg)
            if extra:
                txt.insert("end", f"... and {extra} more\n", "info")
            txt.config(state="disabled")

        # buttons
        def close(_e=None):
            self.popup = None
            flash_taskbar(self, stop=True)
            try:
                pop.destroy()
            except Exception:
                pass

        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", pady=(px(16), 0))
        for c in range(2):
            row.columnconfigure(c, weight=1, uniform="b")
        folder = res.get("folder")
        b1 = Btn(row, "Open folder", lambda: open_path(folder), height=36, width=px(120), bg=PANEL)
        b1.grid(row=0, column=0, sticky="ew", padx=(0, px(5)))
        Btn(row, "Close", close, kind="primary", height=36, width=px(120), bg=PANEL
            ).grid(row=0, column=1, sticky="ew", padx=(px(5), 0))
        b1.set_enabled(bool(folder))

        pop.protocol("WM_DELETE_WINDOW", close)
        pop.bind("<Escape>", close)

        # center over the app (or the screen if the app is minimized), then bring it to the front
        pop.update_idletasks()
        w, h = pop.winfo_reqwidth(), pop.winfo_reqheight()
        if self.state() == "normal":
            x = self.winfo_rootx() + (self.winfo_width() - w) // 2
            y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        else:
            x = (pop.winfo_screenwidth() - w) // 2
            y = (pop.winfo_screenheight() - h) // 2
        pop.geometry(f"+{max(0, x)}+{max(0, y)}")
        pop.attributes("-topmost", True)
        pop.lift()
        pop.after(1500, lambda: pop.winfo_exists() and pop.attributes("-topmost", False))

    def finish(self, text, good=True):
        """good: True = green, False = red, None = amber (stopped by the user)."""
        self.running = False
        self.paused = False
        self.stopping = False
        self.ctrl.pack_forget()
        self.btnrow.pack(fill="x", before=self.note)
        self.btn.set_text("⚡  Embed Metadata")
        self.btn.set_enabled(True)
        self.status.config(text=text, fg=OK if good else (WARN if good is None else BAD))
        if good:
            self.frac = 1.0
            self.draw_bar()
            self.pct.config(text="100%")

    def toggle_pause(self):
        if not self.running or self.stopping:
            return
        self.paused = not self.paused
        if self.paused:
            self.pause_btn.set_text("▶  Resume")
            self.flash("Pausing after the current file...", WARN)
        else:
            self.pause_btn.set_text("⏸  Pause")
            self.flash("Resuming...", OK)

    def stop_run(self):
        if not self.running or self.stopping:
            return
        self.stopping = True
        self.paused = False
        self.pause_btn.set_enabled(False)
        self.stop_btn.set_text("Stopping...")
        self.stop_btn.set_enabled(False)
        self.flash("Stopping after the current file...", WARN)

    def checkpoint(self, done, total):
        """Called by the worker between files. Returns False if the user pressed Stop."""
        if self.paused and not self.stopping:
            self.write("[PAUSED] Paused. Click Resume to continue.")
            self.set_progress(done, total, f"Paused at {done}/{total}  -  click Resume to continue")
            while self.paused and not self.stopping:
                time.sleep(0.15)
            if not self.stopping:
                self.write("[RESUMED] Resumed.")
        return not self.stopping

    # ---------------------------------------------------------------- run
    def start(self):
        if self.running:
            return
        if not self.sources:
            self.flash("Select files or a folder first (drag & drop or Browse).")
            return
        if not self.csv_path or not self.csv_path.is_file():
            self.flash("Select a CSV file first (you can pick it together with the files).")
            return

        self.running = True
        self.paused = False
        self.stopping = False
        self.btnrow.pack_forget()
        self.pause_btn.set_text("⏸  Pause")
        self.pause_btn.set_enabled(True)
        self.stop_btn.set_text("⏹  Stop")
        self.stop_btn.set_enabled(True)
        self.ctrl.pack(fill="x", before=self.note)
        self.clear_log()
        self.run_lines = []
        self.run_started = time.time()
        first = self.sources[0]
        self.last_folder = first if first.is_dir() else first.parent
        self.frac = 0.0
        self.draw_bar()
        self.set_counts(0, 0, 0, 0)
        if not shutil.which("exiftool"):
            self.write("ExifTool not found: JPG / PNG / MP4 / MOV / AI will not work "
                       "(EPS, SVG, WebM will). Place exiftool.exe next to the app.", "warn")
        threading.Thread(target=self.worker, args=(list(self.sources), self.csv_path),
                         daemon=True).start()

    def collect_files(self, sources):
        """Return: files {naam: [(path, root)]}, nfiles, nsub, has_folder."""
        files, seen, nsub, has_folder = {}, set(), set(), False
        for src in sources:
            if src.is_dir():
                has_folder = True
                it = src.rglob("*") if self.sub_var.get() else src.glob("*")
                for p in it:
                    if not p.is_file() or "_backup_originals" in p.relative_to(src).parts:
                        continue
                    key = str(p.resolve()).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    files.setdefault(p.name.lower(), []).append((p, src))
                    if p.parent != src:
                        nsub.add(p.parent)
            elif src.is_file():
                key = str(src.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                files.setdefault(src.name.lower(), []).append((src, src.parent))
        total = sum(len(v) for v in files.values())
        return files, total, len(nsub), has_folder

    def worker(self, sources, csv_path):
        ok = fail = missing = 0
        fail_items, missing_items = [], []
        try:
            self.write("Building file list...")
            files, nfiles, nsub, has_folder = self.collect_files(sources)
            extra = f" (including {nsub} subfolders)" if nsub else ""
            self.write(f"Found {nfiles} files{extra}.")

            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            total = len(rows)
            self.write(f"Found {total} rows in the CSV.\n")
            self.set_counts(total, 0, 0, 0)

            quiet = not has_folder     # if only some files were given, don't show [MISSING] for the other rows
            skipped_rows = 0
            matched = set()
            stopped_at = None
            for i, raw in enumerate(rows, 1):
                if not self.checkpoint(i - 1, total):
                    stopped_at = i - 1
                    break
                row = {k.strip().lower(): (v or "") for k, v in raw.items() if k}
                if self.rating_var.get():
                    row["rating"] = "5"
                name = row.get("filename", "").strip()
                self.set_progress(i - 1, total, f"{i}/{total}   {name}")

                # works even if the CSV has "sub/name.eps"
                norm = name.replace("\\", "/")
                base = norm.rsplit("/", 1)[-1].lower()
                cands = files.get(base, [])
                if "/" in norm:
                    cands = [c for c in cands if c[0].as_posix().lower().endswith(norm.lower())]
                if not cands:
                    if quiet:
                        skipped_rows += 1
                    else:
                        self.write(f"[MISSING] {name}")
                        missing_items.append(name)
                        missing += 1
                    self.set_counts(total, ok, missing, fail)
                    continue

                for path, root in cands:
                    if self.stopping:
                        break
                    matched.add(path)
                    shown = path.relative_to(root).as_posix() if path != root else path.name
                    try:
                        if self.backup_var.get():
                            rel = path.relative_to(root) if path != root else Path(path.name)
                            dest = root / "_backup_originals" / rel
                            if not dest.exists():
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(path, dest)
                        if process_file(path, row):
                            self.write(f"[OK] {shown}")
                            ok += 1
                        else:
                            self.write(f"[SKIP] {shown} (unsupported format)")
                    except Exception as e:
                        self.write(f"[FAIL] {shown}: {e}")
                        fail_items.append((shown, str(e)))
                        fail += 1
                    self.set_counts(total, ok, missing, fail)

            if stopped_at is None and self.stopping:
                stopped_at = total       # stop pressed during the very last row
            if stopped_at is not None:
                summary = f"Success: {ok}   Missing: {missing}   Failed: {fail}"
                self.write(f"\n[STOPPED] Stopped by user at row {stopped_at}/{total}.\n{summary}")
                self.after(0, lambda: self.finish(f"Stopped at {stopped_at}/{total}  -  " + summary, None))
                return

            if skipped_rows:
                self.write(f"\n{skipped_rows} more CSV rows have no matching file in this selection "
                           f"(this is normal).")

            # files not in the CSV: left untouched
            supported = EXIF_EXT | {".svg", ".webm"}
            untouched = [p for lst in files.values() for p, _r in lst
                         if p not in matched and p.suffix.lower() in supported]
            if untouched:
                self.write(f"\n[UNTOUCHED] {len(untouched)} files are not listed in the CSV and "
                           f"were not changed.")

            summary = f"Success: {ok}   Missing: {missing}   Failed: {fail}"
            self.write(f"\n===== Done =====\n{summary}")
            good = fail == 0
            elapsed = time.time() - self.run_started
            res = {"ok": ok, "missing": missing, "fail": fail, "untouched": len(untouched),
                   "missing_items": missing_items, "fail_items": fail_items,
                   "folder": self.last_folder, "elapsed": elapsed}
            self.after(0, lambda: self.finish(
                ("Done!  " if good else "Done, but there were errors  ") + summary, good))
            if self.notify_var.get():
                self.after(0, lambda: self.notify_done(res))
        except Exception as e:
            self.write(f"ERROR: {e}", "err")
            self.after(0, lambda: self.finish(f"Error: {e}", False))


def main():
    # Sharp text on Windows (DPI aware)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        import faulthandler
        faulthandler.enable(open(APP_DIR / "crash_log.txt", "a"))
    except Exception:
        pass
    try:
        App().mainloop()
    except Exception:
        log_error()
        raise


if __name__ == "__main__":
    main()
