#!/usr/bin/env python3
"""Keep a story's test cases and their results in Xray (Jira test management).

Deterministic, standard library only. The sdlc workflows run it when Xray is
configured (XRAY_CLIENT_ID and XRAY_CLIENT_SECRET set); otherwise it does
nothing. It never fails a run: problems are warnings.

  xray_sync.py plan --plan plans/<id>.md
      When the plan is approved (the build starts). One Xray Test per
      planned test case (each AC, EC and BUG of the plan), linked to the
      story ("tests" it), a Test Plan for the story, and a first Test
      Execution with every test at TODO.

  xray_sync.py results --plan plans/<id>.md --junit "<glob>" --label "PR #30"
      After a test run. Reads the run's JUnit XML files, finds every test
      named for the story (S<n> ...), and imports one Test Execution with
      each test PASSED or FAILED, the failure text, and its screenshots as
      evidence. The execution is linked to the story and its Test Plan.

A test is the same Xray Test from run to run: Generic tests are matched by
their definition, `<plan id> <story> <ID or test name>`. Every test of a
story run in several browsers is one Test: FAILED if any browser failed,
with each browser's screenshot.

Needs XRAY_CLIENT_ID and XRAY_CLIENT_SECRET (an Xray API key), and for the
Test Plan and the links JIRA_BASE_URL, JIRA_USER_EMAIL and JIRA_API_TOKEN.
XRAY_BASE_URL defaults to https://xray.cloud.getxray.app (set it for a
regional Xray, e.g. https://eu.xray.cloud.getxray.app).
"""
import argparse
import base64
import datetime as dt
import glob
import importlib.util
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_vp_spec = importlib.util.spec_from_file_location("validate_plan", _HERE / "validate_plan.py")
vp = importlib.util.module_from_spec(_vp_spec)
_vp_spec.loader.exec_module(vp)
_ss_spec = importlib.util.spec_from_file_location("spec_stories", _HERE.parents[1] / "write-spec" / "scripts" / "spec_stories.py")
ss = importlib.util.module_from_spec(_ss_spec)
_ss_spec.loader.exec_module(ss)
vi = vp.vi

DEFAULT_XRAY = "https://xray.cloud.getxray.app"
ATTACHMENT_RE = re.compile(r"\[\[ATTACHMENT\|(.+?)\]\]")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_EVIDENCE = 6                    # screenshots per test
MAX_EVIDENCE_BYTES = 3 * 1024 * 1024


def warn(msg):
    print(f"::warning title=Xray::{msg}")


# --------------------------------------------------------------- the plan

def read_plan(path):
    """{id, story, jira, title, cases: [{id, title}]} from a plan file."""
    fm, body = vi.parse_frontmatter(Path(path).read_text(encoding="utf-8"))
    fm = fm or {}
    _, sections = vi.split_sections(body or "")
    title = re.search(r"^# Plan: S\d+ (.+)$", body or "", re.MULTILINE)
    cases = [{"id": f"AC-{m.group(1)}", "title": m.group(2).strip()}
             for m in vp.AC_ROW_RE.finditer(sections.get("Tests", ""))]
    for fid, row in vp.review_findings(body or "").items():
        if not vp.DECISION_RE.match(row["handling"]):
            cases.append({"id": fid, "title": row["finding"]})
    jira = fm.get("jira", "")
    return {"id": fm.get("id") or Path(path).stem, "story": fm.get("story", ""),
            "jira": jira if vi.JIRA_RE.match(jira or "") else "", "title": title.group(1).strip() if title else "",
            "cases": cases}


def project_of(key):
    return key.split("-", 1)[0] if key else ""


def definition(plan, ident):
    """The stable identity of a test in Xray (Generic tests are matched by it)."""
    return f"{plan['id']} {plan['story']} {ident}" if re.match(r"^(AC|EC|BUG)-\d+$", ident) else f"{plan['id']} {ident}"


def summary(plan, ident, title):
    text = f"{plan['story']} {ident}: {title}" if re.match(r"^(AC|EC|BUG)-\d+$", ident) else ident
    return text if len(text) <= 250 else text[:247] + "..."


def test_info(plan, ident, title):
    return {"projectKey": project_of(plan["jira"]), "type": "Generic", "summary": summary(plan, ident, title),
            "definition": definition(plan, ident), "requirementKeys": [plan["jira"]] if plan["jira"] else [],
            "labels": ["sdlc", f"sdlc-{plan['id']}"]}


# ------------------------------------------------------------ JUnit results

def case_id(story, name):
    """AC-k, EC-k or BUG-k when the test is named for one, else None."""
    m = re.search(rf"(?i)(?<![a-z0-9]){story}[ _-]?(ac|ec|bug)[ _-]?(\d+)(?!\d)", name)
    return f"{m.group(1).upper()}-{m.group(2)}" if m else None


def story_title(story, name):
    """The test's own title ('S5 AC-1: ...') from a runner name that may carry its describe path."""
    parts = [p.strip() for p in re.split(r" > | › ", name) if p.strip()]
    for p in reversed(parts):
        if re.match(rf"(?i)^{story}(?!\d)", p):
            return p
    return None


def parse_junit(paths, story):
    """{key: {title, status, messages, evidence, runs}} for every test named for the story.

    key is AC-k / EC-k / BUG-k, or the test's title. A test run in several
    projects (browsers) or files is merged: FAILED if any run failed.
    """
    out = {}
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as e:
            warn(f"could not read {path}: {e}")
            continue
        for suite in root.iter("testsuite"):
            where = suite.get("hostname") or suite.get("name") or ""
            for case in suite.iter("testcase"):
                name = case.get("name") or ""
                title = story_title(story, name)
                if not title:
                    continue
                key = case_id(story, title) or title
                entry = out.setdefault(key, {"title": title, "status": "PASSED", "messages": [], "evidence": [], "runs": 0})
                entry["runs"] += 1
                failure = case.find("failure")
                if failure is None:
                    failure = case.find("error")
                if failure is not None:
                    entry["status"] = "FAILED"
                    text = (failure.get("message") or "") + "\n" + (failure.text or "")
                    entry["messages"].append(f"[{where}] {text.strip()[:1500]}")
                elif case.find("skipped") is not None:
                    entry["runs"] -= 1
                for el in (case.find("system-out"), case.find("system-err")):
                    for m in ATTACHMENT_RE.finditer((el.text or "") if el is not None else ""):
                        entry["evidence"].append((m.group(1).strip(), where))
    for entry in out.values():
        if entry["runs"] == 0:
            entry["status"] = "TODO"
    return out


def find_file(path):
    """An attachment path from another job's runner: as written, or relative to this checkout."""
    if os.path.isfile(path):
        return path
    parts = Path(path).parts
    for i in range(len(parts)):
        candidate = Path(*parts[i:])
        if candidate.is_file():
            return str(candidate)
    return None


def evidence(items):
    """Xray evidence objects (base64) for the images, within the size limits."""
    out, seen = [], set()
    for path, where in items:
        found = find_file(path)
        ext = Path(path).suffix.lower()
        if not found or ext not in IMAGE_TYPES or found in seen or len(out) >= MAX_EVIDENCE:
            continue
        data = Path(found).read_bytes()
        if len(data) > MAX_EVIDENCE_BYTES:
            continue
        seen.add(found)
        tag = re.sub(r"[^A-Za-z0-9_.-]+", "-", where).strip("-") or "run"
        out.append({"data": base64.b64encode(data).decode("ascii"), "filename": f"{tag}-{Path(found).name}",
                    "contentType": IMAGE_TYPES[ext]})
    return out


def execution_payload(plan, results, label, revision="", run_url="", test_plan=None, planned=False):
    """The Xray JSON import for one Test Execution."""
    tests = []
    titles = {c["id"]: c["title"] for c in plan["cases"]}
    keys = list(titles) + [k for k in results if k not in titles]
    for key in keys:
        res = results.get(key)
        title = titles.get(key) or (res and res["title"]) or key
        test = {"testInfo": test_info(plan, key, title)}
        if planned or res is None:
            test["status"] = "TODO"
            if not planned:
                test["comment"] = "No test with this name ran."
        else:
            test["status"] = res["status"]
            comment = f"{res['runs']} run(s)."
            if res["messages"]:
                comment += "\n\n" + "\n\n".join(res["messages"])[:6000]
            test["comment"] = comment
            ev = evidence(res["evidence"])
            if ev:
                test["evidence"] = ev
        tests.append(test)
    passed = sum(t["status"] == "PASSED" for t in tests)
    failed = sum(t["status"] == "FAILED" for t in tests)
    result = "planned, not run yet" if planned else f"{passed} passed, {failed} failed of {len(tests)}"
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    info = {"project": project_of(plan["jira"]),
            "summary": f"{plan['story']} {plan['title']}: {label} ({result})"[:250],
            "description": (f"Story {plan['jira']}, plan {plan['id']}. " + (f"Run: {run_url}" if run_url else "")).strip(),
            "startDate": now, "finishDate": now}
    if revision:
        info["revision"] = revision
    if test_plan:
        info["testPlanKey"] = test_plan
    return {"info": info, "tests": tests}


# ------------------------------------------------------------------ the APIs

class Xray:
    def __init__(self, client_id, client_secret, base=DEFAULT_XRAY):
        self.base = base.rstrip("/")
        token = self._post("/api/v2/authenticate", {"client_id": client_id, "client_secret": client_secret})
        self.token = token if isinstance(token, str) else str(token)

    def _post(self, path, body, token=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Xray {path}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:500]}")
        except urllib.error.URLError as e:
            raise SystemExit(f"Xray {path}: {e.reason}")

    def import_execution(self, payload):
        return self._post("/api/v2/import/execution", payload, self.token)


def jira_from_env():
    env = {k: os.environ.get(k, "") for k in ("JIRA_BASE_URL", "JIRA_USER_EMAIL", "JIRA_API_TOKEN")}
    return ss.Jira(env["JIRA_BASE_URL"], env["JIRA_USER_EMAIL"], env["JIRA_API_TOKEN"]) if all(env.values()) else None


def find_test_plan(jira, plan):
    jql = f'project = "{project_of(plan["jira"])}" AND issuetype = "Test Plan" AND labels = "sdlc-{plan["id"]}"'
    found = jira.call("GET", "/rest/api/3/search/jql?maxResults=1&fields=key&jql=" + urllib.request.quote(jql))
    issues = (found or {}).get("issues") or []
    return issues[0]["key"] if issues else None


def link(jira, from_key, to_key):
    """'from_key relates to to_key' (Relates exists in every Jira)."""
    jira.call("POST", "/rest/api/2/issueLink", {"type": {"name": "Relates"},
                                                "inwardIssue": {"key": from_key}, "outwardIssue": {"key": to_key}})


def ensure_test_plan(jira, plan):
    key = find_test_plan(jira, plan)
    if key:
        return key
    created = jira.call("POST", "/rest/api/2/issue", {"fields": {
        "project": {"key": project_of(plan["jira"])}, "issuetype": {"name": "Test Plan"},
        "summary": f"{plan['story']} {plan['title']}: tests"[:250],
        "description": f"The tests of story {plan['jira']} (plan {plan['id']}), kept by the sdlc plugin.",
        "labels": ["sdlc", f"sdlc-{plan['id']}"]}})
    key = created["key"]
    link(jira, key, plan["jira"])
    return key


# --------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["plan", "results"])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--junit", default="", help="results: glob(s) of JUnit XML files, space separated")
    ap.add_argument("--label", default="", help="results: where the run happened, e.g. 'PR #30' or 'main'")
    ap.add_argument("--revision", default="")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--dry-run", action="store_true", help="print the import instead of sending it")
    args = ap.parse_args(argv)

    client_id, secret = os.environ.get("XRAY_CLIENT_ID", ""), os.environ.get("XRAY_CLIENT_SECRET", "")
    if not (client_id and secret) and not args.dry_run:
        print("Xray not configured (XRAY_CLIENT_ID, XRAY_CLIENT_SECRET); skipping.")
        return 0
    plan = read_plan(args.plan)
    if not plan["jira"]:
        print(f"{args.plan} has no Jira key: Xray tests are kept under Jira stories; skipping.")
        return 0

    if args.mode == "plan":
        results, label, planned = {}, "planned tests", True
    else:
        paths = sorted({p for pattern in args.junit.split() for p in glob.glob(pattern, recursive=True)})
        if not paths:
            warn(f"no JUnit results matched {args.junit!r} (results_path in .sdlc/build.yaml): nothing to record.")
            return 0
        results, label, planned = parse_junit(paths, plan["story"]), args.label or "test run", False

    if args.dry_run:
        payload = execution_payload(plan, results, label, args.revision, args.run_url, None, planned)
        for t in payload["tests"]:
            for e in t.get("evidence", []):
                e["data"] = f"<{len(e['data'])} base64 chars>"
        print(json.dumps(payload, indent=2))
        return 0
    try:
        jira = jira_from_env()
        test_plan = None
        if jira:
            try:
                test_plan = ensure_test_plan(jira, plan) if planned else find_test_plan(jira, plan)
            except SystemExit as e:
                warn(f"no Test Plan for {plan['jira']} ({e}); recording the execution without one.")
        xray = Xray(client_id, secret, os.environ.get("XRAY_BASE_URL") or DEFAULT_XRAY)
        payload = execution_payload(plan, results, label, args.revision, args.run_url, test_plan, planned)
        created = xray.import_execution(payload) or {}
        key = created.get("key", "")
        if jira and key:
            try:
                link(jira, key, plan["jira"])
            except SystemExit as e:
                warn(f"could not link {key} to {plan['jira']}: {e}")
        counts = {s: sum(t["status"] == s for t in payload["tests"]) for s in ("PASSED", "FAILED", "TODO")}
        print(f"Xray: {key or 'execution'} for {plan['jira']} ({label}): {counts['PASSED']} passed, "
              f"{counts['FAILED']} failed, {counts['TODO']} not run" + (f"; Test Plan {test_plan}" if test_plan else ""))
    except SystemExit as e:
        warn(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
