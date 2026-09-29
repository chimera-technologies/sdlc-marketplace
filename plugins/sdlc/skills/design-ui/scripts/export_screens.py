#!/usr/bin/env python3
"""Export every screen in designs/<slug>/design.md from Figma as a PNG.

Deterministic, standard library only. The design-ui skill runs it after
the screens are built in Figma; re-run it whenever a screen changes.

  FIGMA_TOKEN=<personal access token> python export_screens.py designs/<slug>/design.md

The token needs the `file_content:read` scope (Figma > Settings > Security >
Personal access tokens). It is read from the environment only and never
printed. Uses Figma's REST image export:
  GET https://api.figma.com/v1/images/<file_key>?ids=<node,...>&format=png&scale=<n>
and writes designs/<slug>/screens/<screen>.png for each row of the Screens
table.

Exit 0 = all screens exported, 1 = error.
"""
import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_VD_PATH = Path(__file__).resolve().parent / "validate_design.py"
_spec = importlib.util.spec_from_file_location("validate_design", _VD_PATH)
vd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vd)

API = "https://api.figma.com/v1"


def get(url, token=None, timeout=60):
    headers = {"X-Figma-Token": token} if token else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        # Never echo the request headers (they hold the token).
        raise SystemExit(f"Figma request failed: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")


def plan_exports(manifest):
    """(file_key, [(screen, api_node_id, out_path)]) from the manifest."""
    text = Path(manifest).read_text(encoding="utf-8")
    fm, body = vd.vi.parse_frontmatter(text)
    if not fm or not fm.get("figma_file_key"):
        raise SystemExit("manifest has no figma_file_key")
    rows = vd.parse_screens(body)
    if not rows:
        raise SystemExit("manifest has no screens")
    base = Path(manifest).parent
    return fm["figma_file_key"], [(r["screen"], vd.normalize_node(r["node"]), base / r["screenshot"]) for r in rows]


def export(manifest, token, scale=2, fetch=get):
    key, items = plan_exports(manifest)
    ids = ",".join(node for _, node, _ in items)
    url = f"{API}/images/{urllib.parse.quote(key)}?ids={urllib.parse.quote(ids, safe=',:')}&format=png&scale={scale}"
    data = json.loads(fetch(url, token))
    if data.get("err"):
        raise SystemExit(f"Figma could not render images: {data['err']}")
    images = data.get("images") or {}
    written = []
    for screen, node, out in items:
        src = images.get(node)
        if not src:
            raise SystemExit(f"Figma returned no image for screen {screen!r} (node {node}); check the node id")
        png = fetch(src)  # a pre-signed URL: no token sent
        if png[:8] != vd.PNG_MAGIC:
            raise SystemExit(f"screen {screen!r}: download is not a PNG")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
        written.append((screen, out, len(png)))
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    ap.add_argument("--scale", type=float, default=2, help="1 to 4 (default 2)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be exported")
    args = ap.parse_args()
    if args.dry_run:
        key, items = plan_exports(args.manifest)
        for screen, node, out in items:
            print(f"{screen}: node {node} -> {out.as_posix()}")
        return 0
    token = os.environ.get("FIGMA_TOKEN", "")
    if not token:
        print("FIGMA_TOKEN is not set. Create a Figma personal access token with the "
              "file_content:read scope and set it in your environment (not in a file).", file=sys.stderr)
        return 1
    try:
        written = export(args.manifest, token, args.scale)
    except SystemExit as e:
        print(f"Export failed: {e}", file=sys.stderr)
        return 1
    for screen, out, size in written:
        print(f"OK {screen} -> {out.as_posix()} ({size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
