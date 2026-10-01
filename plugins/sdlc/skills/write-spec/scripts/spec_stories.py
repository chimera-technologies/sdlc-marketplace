#!/usr/bin/env python3
"""Create Jira stories from a spec's Work breakdown (Design -> Build).

Deterministic: no model involved. Run by the spec-to-stories workflow when a
spec is merged. Standard library only.

Usage:
  spec_stories.py specs/foo.md --list                  # print stories as JSON
  spec_stories.py specs/foo.md --create [--dry-run]    # create in Jira

--create needs JIRA_BASE_URL, JIRA_USER_EMAIL and JIRA_API_TOKEN in the
environment, and either the spec's record_id (the intent's Jira record) or
--jira-config .sdlc/jira.yaml (enabled: true, space_key).

- No record_id: with --jira-config, the Epic is created here, in space_key,
  labelled spec-<slug> (and created_label), and the stories go under it. A
  re-run finds that Epic by its label instead of creating another.
- Idempotent: each story carries the label spec-<slug>-<sN>; a story whose
  label already exists is skipped, so re-runs and spec revisions only add
  new stories.
- If the record is an Epic, stories are created under it (parent). If it
  is any other issue type, stories are created in the same space and
  linked to it with "Relates".
Prints a JSON summary: {"record": ..., "epic_created": ..., "created": [...], "existing": [...]}.
"""
import argparse
import base64
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_VS_PATH = Path(__file__).resolve().parent / "validate_spec.py"
_spec = importlib.util.spec_from_file_location("validate_spec", _VS_PATH)
vs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vs)


def story_payloads(spec_path, issue_type="Story"):
    """Story fields for each '### S<n>:' entry in the spec (no Jira calls)."""
    text = Path(spec_path).read_text(encoding="utf-8")
    fm, body = vs.vi.parse_frontmatter(text)
    fm = fm or {}
    slug = fm.get("id", Path(spec_path).stem)
    out = []
    for s in vs.parse_stories(body):
        label = f"spec-{slug}-{s['id'].lower()}"
        out.append({
            "id": s["id"],
            "label": label,
            "summary": f"{s['id']}: {s['title']}"[:255],
            "description": f"{s['body']}\n\nFrom spec: specs/{slug}.md ({s['id']})",
            "labels": ["from-spec", label],
            "issue_type": issue_type,
        })
    return fm, out


class Jira:
    def __init__(self, base_url, email, token, dry_run=False):
        self.base = base_url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
        self.dry_run = dry_run

    def call(self, method, path, body=None):
        if self.dry_run and method != "GET":
            print(f"DRY-RUN {method} {path} {json.dumps(body)[:300]}", file=sys.stderr)
            return {"key": "DRY-RUN"}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": self.auth, "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Jira {method} {path} failed: {e.code} {e.read().decode(errors='replace')[:500]}")
        except urllib.error.URLError as e:
            raise SystemExit(f"Jira {method} {path} failed: cannot reach {self.base} ({e.reason})")

    def issue(self, key):
        return self.call("GET", f"/rest/api/2/issue/{key}?fields=issuetype,project")

    def find_by_label(self, label):
        jql = urllib.parse.quote(f'labels = "{label}"')
        res = self.call("GET", f"/rest/api/3/search/jql?jql={jql}&fields=key&maxResults=1")
        issues = res.get("issues") or []
        return issues[0]["key"] if issues else None


def load_jira_config(path):
    """Flat `key: value` pairs from .sdlc/jira.yaml ({} if absent)."""
    cfg = {}
    p = Path(path)
    if not p.is_file():
        return cfg
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, _, val = line.partition(":")
        cfg[key.strip()] = val.strip().strip("'\"")
    return cfg


def ensure_epic(spec_path, fm, body, jira, cfg):
    """The spec's Epic: found by its spec-<slug> label, or created in space_key. (key, created)."""
    slug = fm.get("id", Path(spec_path).stem)
    label = f"spec-{slug}"
    key = jira.find_by_label(label)
    if key:
        return key, False
    m = re.search(r"^# Spec: (.+)$", body or "", re.MULTILINE)
    title = (m.group(1) if m else fm.get("title") or slug).strip()
    summary_text = vs.vi.split_sections(body or "")[1].get("Summary", "").strip()
    labels = ["from-spec", label] + ([cfg["created_label"]] if cfg.get("created_label") else [])
    new = jira.call("POST", "/rest/api/2/issue", {"fields": {
        "project": {"key": cfg["space_key"]},
        "issuetype": {"name": cfg.get("epic_issue_type") or "Epic"},
        "summary": title[:255],
        "description": f"{summary_text}\n\nSpec: specs/{slug}.md (intent: {fm.get('intent', 'none')})",
        "labels": labels,
    }})
    return new["key"], True


def create_stories(spec_path, jira, issue_type="Story", jira_cfg=None):
    fm, stories = story_payloads(spec_path, issue_type)
    record = fm.get("record_id", "none")
    epic_created = False
    if record in ("", "none"):
        cfg = jira_cfg or {}
        if str(cfg.get("enabled", "")).lower() != "true" or not cfg.get("space_key"):
            return {"record": None, "created": [], "existing": [], "skipped": "spec has no record_id"}
        _, body = vs.vi.parse_frontmatter(Path(spec_path).read_text(encoding="utf-8"))
        record, epic_created = ensure_epic(spec_path, fm, body, jira, cfg)
        project, is_epic = cfg["space_key"], True
    else:
        rec = jira.issue(record)
        project = rec["fields"]["project"]["key"]
        is_epic = rec["fields"]["issuetype"]["name"].lower() == "epic"
    created, existing = [], []
    for s in stories:
        key = jira.find_by_label(s["label"])
        if key:
            existing.append({"id": s["id"], "key": key})
            continue
        fields = {
            "project": {"key": project},
            "issuetype": {"name": s["issue_type"]},
            "summary": s["summary"],
            "description": s["description"],
            "labels": s["labels"],
        }
        if is_epic:
            fields["parent"] = {"key": record}
        new = jira.call("POST", "/rest/api/2/issue", {"fields": fields})
        if not is_epic:
            jira.call("POST", "/rest/api/2/issueLink", {
                "type": {"name": "Relates"}, "inwardIssue": {"key": new["key"]}, "outwardIssue": {"key": record}})
        created.append({"id": s["id"], "key": new["key"], "summary": s["summary"]})
    return {"record": record, "epic_created": epic_created, "parent": is_epic, "created": created, "existing": existing}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--create", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="with --create: read from Jira, print writes, change nothing")
    ap.add_argument("--issue-type", default="Story")
    ap.add_argument("--jira-config", help=".sdlc/jira.yaml: create the Epic when the spec has no record_id")
    args = ap.parse_args()

    if args.list:
        _, stories = story_payloads(args.spec, args.issue_type)
        print(json.dumps(stories, indent=2))
        return
    env = {k: os.environ.get(k, "") for k in ("JIRA_BASE_URL", "JIRA_USER_EMAIL", "JIRA_API_TOKEN")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit(f"missing environment: {', '.join(missing)}")
    jira = Jira(env["JIRA_BASE_URL"], env["JIRA_USER_EMAIL"], env["JIRA_API_TOKEN"], args.dry_run)
    cfg = load_jira_config(args.jira_config) if args.jira_config else None
    issue_type = (cfg or {}).get("story_issue_type") or args.issue_type
    print(json.dumps(create_stories(args.spec, jira, issue_type, cfg), indent=2))


if __name__ == "__main__":
    main()
