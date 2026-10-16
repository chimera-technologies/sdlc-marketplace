#!/usr/bin/env python3
"""PR review findings as PR comments the reviewer acts on.

Deterministic, standard library only. Used by sdlc-pr (the review gate) and
sdlc-fix-findings (the reviewer's commands).

  findings.py comments .sdlc-output/pr-review.json --sha <head sha> --out comments.json
      One comment body per high or medium finding, numbered 1..n, each with
      a marker the commands find it by. Low findings stay in the summary.

  findings.py command "<comment text>"
      Parse a reviewer's command: {"action": "fix" | "dismiss", "numbers":
      [1, 2], "text": "<the rest>"}, or {} if the comment is not one.

  findings.py pick --comments pr-comments.json --numbers 1 2 --out findings.md
      The findings with those numbers from the latest review (the newest
      marker sha), as markdown for the fix.

  findings.py dismissed --comments pr-comments.json --out dismissed.md
      Every finding a trusted reviewer dismissed on this PR, with the reason,
      for the next review not to report again.

pr-comments.json is `gh api repos/<repo>/issues/<pr>/comments --paginate`
(merged into one list): id, body, created_at, author_association, user.login.
"""
import argparse
import json
import re
import sys
from pathlib import Path

MARKER_RE = re.compile(r"<!-- sdlc-finding n=(\d+) sha=([0-9a-f]+) severity=(\w+) -->")
COMMAND_RE = re.compile(r"^\s*/sdlc\s+(fix|dismiss)\b(.*)$", re.IGNORECASE | re.DOTALL)
NUMBERS_RE = re.compile(r"^[\s,]*((?:\d+|all)(?:\s*[, ]\s*\d+)*)\s*[:\-]?\s*", re.IGNORECASE)
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
ICON = {"high": "🔴", "medium": "🟠"}


def load_review(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [f for f in data.get("findings", []) if isinstance(f, dict)] if isinstance(data, dict) else []


def comments(findings, sha):
    """[{n, severity, body}] for each high or medium finding, high first."""
    order = {"high": 0, "medium": 1}
    act = sorted((f for f in findings if str(f.get("severity", "")).lower() in order),
                 key=lambda f: order[str(f["severity"]).lower()])
    out = []
    for n, f in enumerate(act, 1):
        sev = str(f["severity"]).lower()
        short = sha[:7]
        lines = [f"<!-- sdlc-finding n={n} sha={sha} severity={sev} -->",
                 f"### {ICON[sev]} Review finding {n} ({sev}): {f.get('section', '').strip()}", "",
                 str(f.get("issue", "")).strip(), ""]
        if f.get("evidence"):
            lines += [f"**Evidence:** {str(f['evidence']).strip()}", ""]
        if f.get("suggestion"):
            lines += [f"**Suggestion:** {str(f['suggestion']).strip()}", ""]
        lines += ["**Reviewer, what should happen?** Reply with a comment:",
                  f"- `/sdlc fix {n}`: the bot fixes it on this branch as suggested",
                  f"- `/sdlc fix {n} <how>`: the bot fixes it your way (for example `/sdlc fix {n} keep the links, update the design`)",
                  f"- `/sdlc dismiss {n} <reason>`: accept it as it is; the next review will not report it again",
                  "", f"_From the review of `{short}`. Several at once: `/sdlc fix 1 2`._"]
        out.append({"n": n, "severity": sev, "body": "\n".join(lines)})
    return out


def parse_command(text):
    """{"action", "numbers", "text"} for '/sdlc fix 1 2 <how>' or '/sdlc dismiss 1 <why>', else {}."""
    m = COMMAND_RE.match(text or "")
    if not m:
        return {}
    rest = m.group(2)
    nums = NUMBERS_RE.match(rest)
    numbers, all_ = [], False
    if nums and nums.group(1).strip():
        for tok in re.split(r"[\s,]+", nums.group(1).strip()):
            if tok.lower() == "all":
                all_ = True
            elif tok.isdigit():
                numbers.append(int(tok))
        rest = rest[nums.end():]
    return {"action": m.group(1).lower(), "numbers": sorted(set(numbers)), "all": all_, "text": rest.strip()}


def finding_comments(pr_comments):
    """{n: comment} of the latest review's finding comments (by marker), and that review's sha."""
    found = []
    for c in pr_comments:
        m = MARKER_RE.search(c.get("body") or "")
        if m:
            found.append((c.get("created_at") or "", int(m.group(1)), m.group(2), m.group(3), c))
    if not found:
        return {}, None
    latest_sha = max(found, key=lambda x: x[0])[2]
    return {n: {"severity": sev, "body": c["body"], "id": c.get("id")} for _, n, sha, sev, c in found
            if sha == latest_sha}, latest_sha


def strip_actions(body):
    """A finding comment without its marker and the how-to-act lines."""
    body = MARKER_RE.sub("", body)
    return body.split("**Reviewer, what should happen?**", 1)[0].strip()


def pick(pr_comments, numbers, everything=False):
    current, sha = finding_comments(pr_comments)
    if everything:
        numbers = sorted(current)
    chosen = [(n, current[n]) for n in numbers if n in current]
    missing = [n for n in numbers if n not in current]
    text = "\n\n".join(strip_actions(c["body"]) for _, c in chosen)
    return text, [n for n, _ in chosen], missing, sha, sorted({c["severity"] for _, c in chosen})


def dismissed(pr_comments):
    """Markdown of every finding a trusted reviewer dismissed on this PR, oldest first."""
    by_marker = {}
    for c in pr_comments:
        m = MARKER_RE.search(c.get("body") or "")
        if m:
            by_marker.setdefault(int(m.group(1)), []).append((c.get("created_at") or "", c["body"]))
    items = []
    for c in sorted(pr_comments, key=lambda c: c.get("created_at") or ""):
        if (c.get("author_association") or "").upper() not in TRUSTED:
            continue
        cmd = parse_command(c.get("body") or "")
        if cmd.get("action") != "dismiss":
            continue
        when = c.get("created_at") or ""
        who = (c.get("user") or {}).get("login", "a reviewer")
        for n in cmd["numbers"]:
            # the finding comment with that number that was current when the reviewer dismissed it
            older = [b for t, b in by_marker.get(n, []) if t <= when]
            if older:
                items.append(f"- Dismissed by @{who}: \"{cmd['text'] or 'no reason given'}\"\n\n"
                             + "\n".join("  > " + line for line in strip_actions(older[-1]).splitlines()))
    return "\n\n".join(items)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("comments")
    c.add_argument("review")
    c.add_argument("--sha", required=True)
    c.add_argument("--out", required=True)
    k = sub.add_parser("command")
    k.add_argument("text")
    p = sub.add_parser("pick")
    p.add_argument("--comments", required=True)
    p.add_argument("--numbers", nargs="*", type=int, default=[])
    p.add_argument("--all", action="store_true")
    p.add_argument("--out", required=True)
    d = sub.add_parser("dismissed")
    d.add_argument("--comments", required=True)
    d.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.mode == "comments":
        out = comments(load_review(args.review), args.sha)
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(len(out))
        return 0
    if args.mode == "command":
        print(json.dumps(parse_command(args.text)))
        return 0
    pr_comments = json.loads(Path(args.comments).read_text(encoding="utf-8"))
    if args.mode == "pick":
        text, found, missing, sha, severities = pick(pr_comments, args.numbers, args.all)
        Path(args.out).write_text(text, encoding="utf-8")
        print(json.dumps({"found": found, "missing": missing, "sha": sha, "severities": severities}))
        return 0
    Path(args.out).write_text(dismissed(pr_comments), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
