#!/usr/bin/env python3
"""Render every HTML mockup in designs/<slug>/design.md to a PNG.

Deterministic, standard library only. For `source: mockup` manifests: each
screen's mockups/<screen>.html is screenshotted by a headless Chromium-family
browser (Chrome, Chromium or Edge) into screens/<screen>.png. The Design
workflow runs it after the design-ui skill writes the mockups; run it
locally after changing one.

  python render_mockups.py designs/<slug>/design.md
  python render_mockups.py --dry-run designs/<slug>/design.md

The viewport is 1280x800 unless the mockup sets
<meta name="sdlc-size" content="390x844">. Each mockup is checked first
(validate_design.mockup_problems), then a copy is rendered with a
Content-Security-Policy that blocks all scripts and loads, and with every
network request sent to a dead proxy, so the PNG shows only the HTML.

Browser: $SDLC_BROWSER, $CHROME_BIN, or the first of google-chrome,
chromium, chrome, msedge found on PATH or in the usual install folders.

Exit 0 = all screens rendered, 1 = error.
"""
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_VD_PATH = Path(__file__).resolve().parent / "validate_design.py"
_spec = importlib.util.spec_from_file_location("validate_design", _VD_PATH)
vd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vd)

BROWSERS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge", "microsoft-edge"]
INSTALL_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_browser():
    for env in ("SDLC_BROWSER", "CHROME_BIN"):
        if os.environ.get(env):
            return os.environ[env]
    for name in BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    for path in INSTALL_PATHS:
        if Path(path).is_file():
            return path
    return None


def plan_renders(manifest):
    """[(screen, html_path, png_path, (w, h))] from the manifest."""
    manifest = Path(manifest)
    fm, body = vd.vi.parse_frontmatter(manifest.read_text(encoding="utf-8"))
    if not fm or fm.get("source") != "mockup":
        raise SystemExit("manifest is not source: mockup (Figma screens are exported with export_screens.py)")
    rows = vd.parse_screens(body)
    if not rows:
        raise SystemExit("manifest has no screens")
    items = []
    for r in rows:
        html = manifest.parent / r["node"]
        if r["node"] != f"mockups/{r['screen']}.html" or not html.is_file():
            raise SystemExit(f"screen {r['screen']!r}: mockups/{r['screen']}.html not found")
        text = html.read_text(encoding="utf-8", errors="replace")
        problems = vd.mockup_problems(text)
        if problems:
            raise SystemExit(f"screen {r['screen']!r}: {html.as_posix()} {problems[0]}")
        items.append((r["screen"], html.resolve(), manifest.parent / r["screenshot"], vd.mockup_size(text)))
    return items


# Injected into the copy that is rendered: no scripts, no loads of any kind
# except the page's own inline styles and data: images and fonts.
CSP = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
       "style-src 'unsafe-inline'; img-src data:; font-src data:\">")


def locked_copy(html_text):
    """The mockup with the CSP as the first thing in <head>."""
    m = re.search(r"<head\b[^>]*>", html_text, re.I)
    if m:
        return html_text[:m.end()] + CSP + html_text[m.end():]
    return CSP + html_text


def command(browser, html, png, size, profile):
    w, h = size
    cmd = [
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio",
        "--no-first-run", "--no-default-browser-check", "--disable-extensions",
        "--force-device-scale-factor=1", f"--window-size={w},{h}",
        # Belt and braces with the CSP: every request goes to a closed port.
        "--proxy-server=127.0.0.1:9", "--proxy-bypass-list=<-loopback>",
        f"--user-data-dir={profile}", f"--screenshot={Path(png).resolve()}",
    ]
    if os.environ.get("CI"):
        cmd.append("--no-sandbox")   # CI containers often lack user namespaces
    return cmd + [html.as_uri()]


def render(manifest, browser, run=subprocess.run):
    items = plan_renders(manifest)
    written = []
    # Not TemporaryDirectory: on Windows the browser's child processes can
    # still hold the profile open, and ignore_cleanup_errors needs 3.10.
    tmp = tempfile.mkdtemp(prefix="sdlc-mockups-")
    try:
        profile = Path(tmp) / "profile"
        for screen, html, png, size in items:
            png.parent.mkdir(parents=True, exist_ok=True)
            if png.exists():
                png.unlink()
            page = Path(tmp) / f"{screen}.html"
            page.write_text(locked_copy(html.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            r = run(command(browser, page, png, size, profile), capture_output=True, text=True, timeout=90)
            if not png.is_file() or png.read_bytes()[:8] != vd.PNG_MAGIC:
                tail = (r.stderr or "").strip().splitlines()[-3:]
                raise SystemExit(f"screen {screen!r}: browser wrote no PNG (exit {r.returncode}) {' | '.join(tail)}")
            written.append((screen, png, size))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    ap.add_argument("--dry-run", action="store_true", help="list what would be rendered")
    args = ap.parse_args()
    try:
        items = plan_renders(args.manifest)
        if args.dry_run:
            for screen, html, png, (w, h) in items:
                print(f"{screen}: {html.name} {w}x{h} -> {png.as_posix()}")
            return 0
        browser = find_browser()
        if not browser:
            raise SystemExit("no Chrome, Chromium or Edge found; install one or set SDLC_BROWSER to its path")
        written = render(args.manifest, browser)
    except SystemExit as e:
        print(f"Render failed: {e}", file=sys.stderr)
        return 1
    for screen, png, (w, h) in written:
        print(f"OK {screen} -> {png.as_posix()} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
