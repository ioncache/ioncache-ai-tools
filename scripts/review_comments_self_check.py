#!/usr/bin/env python3
"""Exercise review-code posting offline with fake GitHub responses and disposable Git repositories."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import review_comments as rc


RUN = "0123456789abcdef0123456789abcdef"
COMMIT = "a" * 40
PR_URL = "https://github.com/acme/widgets/pull/7"

DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
-old = 1
+new = 1
+extra = 2
 value = 3
 tail = 4
@@ -20,3 +21,3 @@ def later():
 keep = 20
--- removed SQL-style comment line
+-- added SQL-style comment line
 end = 22
diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
index 3333333..4444444 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,2 +1,2 @@
-before = 1
+after = 1
 same = 2
"""

APP_LINES = ["import os", "new = 1", "extra = 2", "value = 3", "tail = 4"]


def finding(fid="COR1", **changes):
    value = {
        "id": fid, "severity": "Medium", "action": "Act", "basis": "inferred",
        "title": "New value drops the old default", "priority": "P2", "effort": "quick",
        "introduced": True, "fix_steps": "Restore the old default in src/app.py.",
        "done_when": "A test reading the default value passes.",
        "summary": "The new value drops the old default.", "next_step": "Keep the old default.",
        "categories": ["correctness"], "sensitive": False,
        "anchor": {"path": "src/app.py", "side": "RIGHT", "start_line": 2, "line": 3},
        "suggestion": None, "prior_thread": None,
    }
    value.update(changes)
    return value


def document(*findings, policy="private", complete=True):
    return {"run": RUN, "reviewed_commit": COMMIT, "policy": policy,
            "coverage": {"complete": complete, "incomplete_categories": [] if complete else ["jsdoc"]},
            "findings": list(findings)}


def facts(**changes):
    value = {"eligible": True, "reasons": [], "repository": "acme/widgets", "number": 7,
             "viewer": "reviewer", "visibility": "PRIVATE", "head": COMMIT,
             "reviewed_commit": COMMIT, "merge_base": "b" * 40, "prior_threads": []}
    value.update(changes)
    return value


def build(*findings, facts_changes=None, policy="private", private=(), exclude=(), complete=True):
    return rc.build(document(*findings, policy=policy, complete=complete), facts(**(facts_changes or {})),
                    DIFF, lambda path: APP_LINES, list(private), exclude)


class FakeGitHub:
    """Answer the helper's GraphQL and REST calls from in-memory state."""

    def __init__(self, **state):
        self.state = {"login": "reviewer", "visibility": "PRIVATE", "pr_state": "OPEN",
                      "head": COMMIT, "base": "b" * 40, "pending": 0, "threads": [[]],
                      "reviews": [], "post_errors": [], "posted": []}
        self.state.update(state)
        self.calls = []

    def __call__(self, endpoint, *, data=None, paginate=False):
        self.calls.append((endpoint, data))
        if endpoint != "graphql":
            return self.create_review(data)
        query, variables = data["query"], data["variables"]
        s = self.state
        if "viewer { login }" in query:
            return {"data": {"viewer": {"login": s["login"]}, "repository": {
                "visibility": s["visibility"], "pullRequest": {
                    "state": s["pr_state"], "url": PR_URL, "baseRefName": "main",
                    "baseRefOid": s["base"], "headRefOid": s["head"]}}}}
        if "states: [PENDING]" in query:
            return {"data": {"repository": {"pullRequest": {"reviews": {"totalCount": s["pending"]}}}}}
        if "reviewThreads" in query:
            index = int(variables["after"] or 0)
            more = index + 1 < len(s["threads"])
            return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "pageInfo": {"hasNextPage": more, "endCursor": str(index + 1)},
                "nodes": s["threads"][index]}}}}}
        if "reviews(author: $login, first: 100" in query:
            return {"data": {"repository": {"pullRequest": {"reviews": {
                "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": s["reviews"]}}}}}
        if "node(id: $id)" in query:
            review = next(r for r in s["reviews"] if r["id"] == variables["id"])
            return {"data": {"node": {"state": review["state"], "body": review["body"], "url": review["url"],
                                      "comments": {"totalCount": len(review["comments"]),
                                                   "pageInfo": {"hasNextPage": False, "endCursor": None},
                                                   "nodes": review["comments"]}}}}
        raise AssertionError(f"Unexpected query: {query}")

    def create_review(self, payload):
        self.state["posted"].append(payload)
        if self.state["post_errors"]:
            status = self.state["post_errors"].pop(0)
            raise rc.ApiError(f"gh: Request failed (HTTP {status})", status)
        review = {"id": f"R{len(self.state['reviews'])}", "state": "COMMENTED", "body": payload["body"],
                  "url": f"{PR_URL}#pullrequestreview-1", "comments": [
                      {"path": c["path"], "line": c["line"], "startLine": c.get("start_line"),
                       "body": c["body"]} for c in payload["comments"]]}
        self.state["reviews"].append(review)
        return {"node_id": review["id"], "html_url": review["url"], "state": "COMMENTED"}


def thread(tid, body, login="reviewer", resolved=False):
    return {"id": tid, "isResolved": resolved, "isOutdated": False, "path": "src/app.py", "line": 2,
            "comments": {"nodes": [{"author": {"login": login}, "body": body, "url": f"{PR_URL}#{tid}"}]}}


class DiffTests(unittest.TestCase):
    def test_hunk_lines_follow_counts_not_dash_prefixes(self):
        files = rc.parse_diff(DIFF)
        self.assertEqual(set(files), {"src/app.py", "new_name.py"})
        app = files["src/app.py"]
        self.assertEqual(app["hunks"][0]["RIGHT"], {1, 2, 3, 4, 5})
        self.assertEqual(app["hunks"][0]["LEFT"], {1, 2, 3, 4})
        self.assertEqual(app["hunks"][1]["LEFT"], {20, 21, 22})
        self.assertEqual(app["hunks"][1]["RIGHT"], {21, 22, 23})
        self.assertTrue(files["new_name.py"]["renamed"])

    def test_anchor_rules(self):
        files = rc.parse_diff(DIFF)
        valid = [{"path": "src/app.py", "side": "RIGHT", "start_line": 2, "line": 3},
                 {"path": "src/app.py", "side": "LEFT", "line": 2},
                 {"path": "new_name.py", "side": "RIGHT", "line": 1}]
        for anchor in valid:
            with self.subTest(anchor=anchor):
                self.assertIsNone(rc.anchor_problem(anchor, files))
        invalid = {
            "range crosses hunks": {"path": "src/app.py", "side": "RIGHT", "start_line": 4, "line": 21},
            "outside diff": {"path": "README.md", "side": "RIGHT", "line": 1},
            "renamed LEFT": {"path": "new_name.py", "side": "LEFT", "line": 1},
            "line not in hunk": {"path": "src/app.py", "side": "RIGHT", "line": 10},
            "reversed range": {"path": "src/app.py", "side": "RIGHT", "start_line": 3, "line": 2},
            "bad side": {"path": "src/app.py", "side": "BOTH", "line": 2},
            "missing": None,
        }
        for name, anchor in invalid.items():
            with self.subTest(name=name):
                self.assertIsNotNone(rc.anchor_problem(anchor, files))

    def test_invalid_anchor_moves_finding_to_summary_without_dropping_it(self):
        result = build(finding("COR1", anchor={"path": "README.md", "side": "RIGHT", "line": 1}),
                       finding("COR2", anchor=None))
        self.assertEqual(result["payload"]["comments"], [])
        self.assertEqual([item["id"] for item in result["outside_diff"]], ["COR1", "COR2"])
        body = result["payload"]["body"]
        self.assertIn("### Findings outside the diff", body)
        self.assertIn("`README.md`", body)
        self.assertIn("finding=COR2 -->", body)


class SuggestionTests(unittest.TestCase):
    def test_valid_suggestion_keeps_exact_text_and_range(self):
        result = build(finding(suggestion="new = 1\nextra = 2  # kept\n"))
        comment = result["payload"]["comments"][0]
        self.assertEqual((comment["start_line"], comment["line"], comment["side"]), (2, 3, "RIGHT"))
        self.assertIn("```suggestion\nnew = 1\nextra = 2  # kept\n```", comment["body"])
        self.assertEqual(result["suggestions_dropped"], [])

    def test_each_drop_rule_keeps_the_finding(self):
        cases = {
            "not Act": finding(action="Decide", suggestion="x = 1"),
            "LEFT side": finding(anchor={"path": "src/app.py", "side": "LEFT", "line": 2}, suggestion="x = 1"),
            "triple backtick": finding(suggestion="```\nx\n```"),
            "unchanged": finding(suggestion="new = 1\nextra = 2"),
            "invalid anchor": finding(anchor={"path": "nope.py", "side": "RIGHT", "line": 1}, suggestion="x"),
            "empty": finding(suggestion="  "),
        }
        for name, item in cases.items():
            with self.subTest(name=name):
                result = build(item)
                self.assertEqual([d["id"] for d in result["suggestions_dropped"]], ["COR1"])
                self.assertNotIn("```suggestion", json.dumps(result["payload"]))
                posted = result["inline"] + [o["id"] for o in result["outside_diff"]]
                self.assertEqual(posted, ["COR1"])


class FormatTests(unittest.TestCase):
    def test_header_title_notes_and_marker_last(self):
        result = build(finding("COR1", related=["COR2"], introduced=False),
                       finding("SEC1", severity="High", action="Investigate", basis="observed",
                               priority="P1", effort="heavy",
                               anchor={"path": "src/app.py", "side": "RIGHT", "line": 4}),
                       facts_changes={"visibility": "PRIVATE"})
        first, second = result["payload"]["comments"]
        self.assertTrue(first["body"].startswith(
            "**COR1 | Medium | P2 | Act | Quick fix**\n\n**New value drops the old default**"))
        self.assertIn("Pre-existing: not introduced by this pull request. Same fix as COR2.", first["body"])
        self.assertTrue(second["body"].startswith("**SEC1 | High | P1 | Investigate | Heavy lift**"))
        self.assertNotIn("inferred", first["body"].split("<details>")[0])
        for comment in (first, second):
            self.assertRegex(rc.final_line(comment["body"]), rc.FINDING_MARKER)
        self.assertNotIn("start_line", second)

    def test_agent_guidance_is_collapsed_and_self_contained_for_act_and_decide(self):
        result = build(finding("COR1", locations=["src/app.py:3", "src/app.py:1-2", "src/other.py:40",
                                                  "src/app.py:9"]),
                       finding("COR2", action="Decide", basis="observed", done_when=None,
                               anchor={"path": "src/app.py", "side": "LEFT", "line": 2}),
                       finding("COR3", action="Investigate", fix_steps=None,
                               anchor={"path": "src/app.py", "side": "RIGHT", "line": 4}))
        act, decide, investigate = (c["body"] for c in result["payload"]["comments"])
        guidance = act.split("<summary>Agent guidance</summary>", 1)[1]
        self.assertTrue(act.index("<details>") < act.index("<!-- review-code:v1"))
        for text in (rc.GUIDANCE_PREAMBLE, "Finding COR1: Medium, P2, Act; inferred from source, not reproduced.",
                     "Location: src/app.py:2-3", "Also affects: src/other.py:40, src/app.py:9",
                     "Problem: The new value drops the old default.", "Fix: Restore the old default",
                     "Done when: A test reading"):
            self.assertIn(text, guidance)
        self.assertIn("Location: src/app.py:2 (deleted lines)", decide)
        self.assertIn("COR2: Medium, P2, Decide; observed.", decide)
        self.assertNotIn("Done when", decide)
        self.assertNotIn("<details>", investigate)

    def test_guidance_fence_outlasts_backticks_in_its_text(self):
        body = build(finding(fix_steps="Replace ```old``` with ````new````"))["payload"]["comments"][0]["body"]
        self.assertIn("`````text\n", body)
        self.assertIn("\n`````\n", body)

    def test_new_fields_are_validated(self):
        cases = [{"priority": "high"}, {"effort": "small"}, {"introduced": "no"},
                 {"title": "two\nlines"}, {"title": ""}, {"fix_steps": None}, {"locations": [3]}]
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    build(finding(**change))

    def test_escaping_mentions_and_html_comments(self):
        text = "ping @octocat and @org/team, not user@example.com or `@decorator` <!-- hidden -->"
        escaped = rc.escape(text)
        self.assertIn("`@octocat`", escaped)
        self.assertIn("`@org/team`", escaped)
        self.assertIn("user@example.com", escaped)
        self.assertIn("`@decorator`", escaped)
        self.assertNotIn("``", escaped)
        self.assertIn("&lt;!-- hidden --&gt;", escaped)

    def test_quoted_marker_in_free_text_is_not_a_marker(self):
        fake = f"<!-- review-code:v1 run={RUN} finding=COR9 -->"
        body = build(finding(summary=f"Text quoting {fake} inline"))["payload"]["comments"][0]["body"]
        self.assertEqual(rc.final_line(body), f"<!-- review-code:v1 run={RUN} finding=COR1 -->")
        visible, guidance = body.split("<details>", 1)
        self.assertNotIn(fake, visible)
        code = guidance.split("```text\n", 1)[1].split("\n```", 1)[0]
        self.assertIn(fake, code)
        self.assertNotIn(fake, guidance.replace(code, ""))

    def test_payload_is_a_pinned_comment_review(self):
        payload = build(finding())["payload"]
        self.assertEqual((payload["event"], payload["commit_id"]), ("COMMENT", COMMIT))
        self.assertEqual(rc.final_line(payload["body"]), rc.run_marker(RUN))

    def test_no_findings_posts_coverage_summary(self):
        result = build(complete=False)
        self.assertEqual(result["payload"]["comments"], [])
        body = result["payload"]["body"]
        self.assertIn("found no reportable findings", body)
        self.assertIn("Coverage: incomplete (jsdoc). This is not a complete review.", body)

    def test_moved_head_is_disclosed(self):
        body = build(finding(), facts_changes={"head": "c" * 40})["payload"]["body"]
        self.assertIn(f"has since moved to `{'c' * 40}`", body)


class DisclosureTests(unittest.TestCase):
    def test_policy_visibility_and_origin_matrix(self):
        expected = {
            ("none", "PRIVATE", True): True, ("none", "PUBLIC", True): True,
            ("private", "PUBLIC", True): False, ("private", "PUBLIC", False): True,
            ("private", None, True): False, ("private", None, False): True,
            ("private", "PRIVATE", False): False, ("private", "INTERNAL", False): False,
            ("all", "PUBLIC", False): False, ("all", None, False): False,
        }
        for (policy, visibility, introduced), withheld in expected.items():
            with self.subTest(policy=policy, visibility=visibility, introduced=introduced):
                result = build(finding("SEC1", sensitive=True, introduced=introduced), policy=policy,
                               facts_changes={"visibility": visibility})
                self.assertEqual(result["withheld"] == ["SEC1"], withheld)

    def test_only_the_adjudicator_marks_sensitivity_and_withheld_text_stays_local(self):
        secret = "Token check is bypassed by an empty header."
        result = build(finding("SEC1", categories=["security"], sensitive=False),
                       finding("SEC2", sensitive=True, introduced=False, summary=secret),
                       facts_changes={"visibility": "PUBLIC"})
        self.assertEqual((result["inline"], result["withheld"]), (["SEC1"], ["SEC2"]))
        body = result["payload"]["body"]
        self.assertIn("1 sensitive findings in code that predates this pull request were withheld "
                      "because this repository is public.", body)
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("SEC2", json.dumps(result["payload"]))
        unknown = build(finding("SEC2", sensitive=True, introduced=False), facts_changes={"visibility": None})
        self.assertIn("visibility could not be confirmed", unknown["payload"]["body"])
        none = build(finding("SEC2", sensitive=True), policy="none")
        self.assertIn("withheld under the `none` policy", none["payload"]["body"])

    def test_anchor_paths_must_be_repository_relative(self):
        for path in ("/Users/someone/repo/src/app.py", "/tmp/elsewhere.py"):
            with self.subTest(path=path):
                result = build(finding(anchor={"path": path, "side": "RIGHT", "line": 2}))
                self.assertEqual(result["rejections"], [{"id": "COR1", "field": "anchor",
                                                         "reason": "anchor path must be repository-relative"}])

    def test_non_integer_anchor_coordinates_keep_the_finding(self):
        item = finding(anchor={"path": "src/app.py", "side": "RIGHT", "start_line": 2, "line": "3"},
                       locations=["src/app.py:1-5"])
        result = build(item)
        self.assertEqual([o["id"] for o in result["outside_diff"]], ["COR1"])
        self.assertIn("Also affects: src/app.py:1-5", result["payload"]["body"])

    def test_posted_text_cannot_name_hidden_findings(self):
        hidden = finding("SEC2", sensitive=True, introduced=False)
        result = build(finding("COR1", fix_steps="Same fix as SEC2."), hidden,
                       facts_changes={"visibility": "PUBLIC"})
        self.assertEqual(result["rejections"], [{"id": "COR1", "field": "fix_steps",
                                                 "reason": "names findings that are not posted: SEC2"}])
        result = build(finding("COR1", related=["SEC2", "COR3"]), hidden, finding("COR3"),
                       facts_changes={"visibility": "PUBLIC"})
        body = result["payload"]["comments"][0]["body"]
        self.assertIn("Same fix as COR3.", body)
        self.assertNotIn("SEC2", json.dumps(result["payload"]))
        excluded = build(finding("COR1", summary="Like COR9 but worse."), finding("COR9"), exclude=("COR9",))
        self.assertIn("names findings that are not posted: COR9", excluded["rejections"][0]["reason"])

    def test_private_paths_are_rejected_but_generic_paths_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root, out = Path(temp) / "repo", Path(temp) / "session" / "out"
            root.mkdir()
            out.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"HOME": str(Path(temp) / "home")}):
                markers = rc.private_markers(root, out)
            for field, text in (("summary", f"see {root}/src/app.py"), ("fix_steps", f"{Path(temp) / 'home'}/.config"),
                                ("done_when", f"{out.parent}/report.json"), ("locations", [f"{root}/a.py:1"])):
                with self.subTest(field=field):
                    result = build(finding(**{field: text}), private=markers)
                    self.assertEqual(result["rejections"][0], {"id": "COR1", "field": field,
                                                               "reason": "contains an absolute local path"})
            result = build(finding(summary="writes /tmp/cache and src/app.py"), private=markers)
            self.assertNotIn("rejections", result)
            excluded = build(finding(summary=f"see {root}"), finding("COR2"), private=markers, exclude=("COR1",))
            self.assertEqual((excluded["inline"], excluded["not_posted"]), (["COR2"], ["COR1"]))
            self.assertIn("1 findings were not posted", excluded["payload"]["body"])


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        self.patch_env = mock.patch.dict(os.environ, self.env)
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)
        self.git("init", "-q", "-b", "main", str(self.root), cwd=None)
        (self.root / "app.py").write_text("one\ntwo\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "feature")
        (self.root / "app.py").write_text("one\nTWO\n")
        self.git("commit", "-qam", "change")
        self.head = self.git("rev-parse", "HEAD").strip()

    def git(self, *args, cwd="root"):
        return subprocess.run(["git", *args], cwd=self.root if cwd == "root" else cwd, check=True,
                              capture_output=True, text=True).stdout

    def context(self, url=PR_URL, **state):
        fake = FakeGitHub(**{"head": self.head, "base": self.base, **state})
        with mock.patch.object(rc, "api", fake):
            return rc.context(url, self.root), fake

    def codes(self, result):
        return [item["code"] for item in result["reasons"]]

    def test_eligible_and_each_blocking_reason(self):
        result, _ = self.context()
        self.assertTrue(result["eligible"], result["reasons"])
        self.assertEqual(result["merge_base"], self.base)
        self.assertEqual(self.codes(self.context(pr_state="CLOSED")[0]), ["state"])
        self.assertEqual(self.codes(self.context(pending=1)[0]), ["pending"])
        self.assertEqual(self.codes(self.context(base="d" * 40)[0]), ["base"])
        moved, _ = self.context()
        self.git("commit", "-q", "--allow-empty", "-m", "local only")
        self.assertEqual(self.codes(self.context()[0]), ["head"])
        self.git("reset", "-q", "--hard", self.head)
        (self.root / "untracked.txt").write_text("x")
        self.assertEqual(self.codes(self.context()[0]), ["dirty"])
        result = rc.context("https://example.com/acme/widgets/pull/7", self.root)
        self.assertEqual(self.codes(result), ["host"])

    def test_merge_base_diff_ignores_base_branch_progress(self):
        self.git("checkout", "-q", "main")
        (self.root / "main_only.py").write_text("x = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "main moves on")
        tip = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "feature")
        result, _ = self.context(base=tip)
        self.assertEqual(result["merge_base"], self.base)
        diff = self.git("diff", "--no-color", "--no-ext-diff", "-M", result["merge_base"], self.head)
        files = rc.parse_diff(diff)
        self.assertEqual(set(files), {"app.py"})
        self.assertIsNone(rc.anchor_problem({"path": "app.py", "side": "RIGHT", "line": 2}, files))

    def test_build_command_reads_the_real_merge_base_diff_and_reviewed_lines(self):
        facts_value, _ = self.context()
        out = Path(self.temp.name) / "session" / "post"
        out.parent.mkdir()
        (out.parent / "context.json").write_text(json.dumps(facts_value))
        item = finding(anchor={"path": "app.py", "side": "RIGHT", "line": 2}, suggestion="Two")
        unchanged = finding("COR2", anchor={"path": "app.py", "side": "RIGHT", "line": 2}, suggestion="TWO")
        value = {**document(item, unchanged), "reviewed_commit": self.head}
        (out.parent / "input.json").write_text(json.dumps(value))
        with contextlib.chdir(self.root), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = rc.main(["build", "--input", str(out.parent / "input.json"),
                            "--context", str(out.parent / "context.json"), "--out", str(out)])
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(out.stat().st_mode & 0o777, 0o700)
        payload = json.loads((out / "payload.json").read_text())
        self.assertEqual([c["path"] for c in payload["comments"]], ["app.py", "app.py"])
        self.assertIn("```suggestion\nTwo\n```", payload["comments"][0]["body"])
        self.assertNotIn("```suggestion", payload["comments"][1]["body"])
        summary = json.loads(stdout.getvalue())
        self.assertEqual(summary["suggestions_dropped"][0]["id"], "COR2")
        self.assertEqual(len(summary["identity"]), 64)

    def test_prior_threads_trust_only_viewer_markers_across_pages(self):
        own = f"text\n<!-- review-code:v1 run={RUN} finding=COR1 -->"
        threads = [[thread("T1", own), thread("T2", own, login="someone-else")],
                   [thread("T3", f"<!-- review-code:v1 run={RUN} finding=COR2 -->\nquoted after"),
                    thread("T4", own.replace("COR1", "SEC2"), resolved=True)]]
        result, _ = self.context(threads=threads)
        self.assertEqual([(t["id"], t["finding"], t["resolved"]) for t in result["prior_threads"]],
                         [("T1", "COR1", False), ("T4", "SEC2", True)])


class PriorThreadTests(unittest.TestCase):
    def test_unresolved_thread_suppresses_and_resolved_does_not(self):
        prior = [{"id": "T1", "url": f"{PR_URL}#T1", "resolved": False},
                 {"id": "T2", "url": f"{PR_URL}#T2", "resolved": True}]
        result = build(finding("COR1", prior_thread="T1"), finding("COR2", prior_thread="T2"),
                       facts_changes={"prior_threads": prior})
        self.assertEqual(result["inline"], ["COR2"])
        self.assertEqual(result["already_raised"], [{"id": "COR1", "url": f"{PR_URL}#T1"}])
        self.assertIn(f"[COR1]({PR_URL}#T1)", result["payload"]["body"])


class PostTests(unittest.TestCase):
    def bundle(self):
        result = build(finding("COR1"), finding("COR2", anchor={"path": "src/app.py", "side": "LEFT", "line": 2}))
        return ({key: result[key] for key in ("payload", "fallback", "visibility")}, result["identity"])

    def post(self, fake, bundle=None, approved=None, **changes):
        bundle, identity = (bundle, approved) if bundle else self.bundle()
        with mock.patch.object(rc, "api", fake):
            return rc.post(facts(**changes), bundle, approved or identity)

    def test_posts_once_and_verifies_read_back(self):
        fake = FakeGitHub()
        receipt = self.post(fake)
        self.assertEqual((receipt["outcome"], receipt["used"], receipt["attempts"]), ("posted", "payload", ["payload"]))
        self.assertEqual(len(fake.state["posted"]), 1)
        self.assertEqual(fake.state["posted"][0]["event"], "COMMENT")
        self.assertEqual(fake.state["posted"][0]["commit_id"], COMMIT)

    def test_identity_must_match_both_files(self):
        bundle, identity = self.bundle()
        bundle["fallback"] = {**bundle["fallback"], "body": "changed"}
        with self.assertRaisesRegex(ValueError, "approved identity"):
            self.post(FakeGitHub(), bundle, identity)

    def test_existing_review_with_run_marker_is_read_back_not_reposted(self):
        fake = FakeGitHub()
        self.post(fake)
        receipt = self.post(fake)
        self.assertEqual((receipt["outcome"], receipt["attempts"]), ("posted", ["already posted"]))
        self.assertEqual(len(fake.state["posted"]), 1)

    def test_422_uses_one_fallback_and_a_second_422_stops(self):
        fake = FakeGitHub(post_errors=[422])
        receipt = self.post(fake)
        self.assertEqual((receipt["outcome"], receipt["used"]), ("posted", "fallback"))
        self.assertEqual(fake.state["posted"][1]["comments"], [])
        self.assertIn("### Findings", fake.state["posted"][1]["body"])
        fake = FakeGitHub(post_errors=[422, 422])
        receipt = self.post(fake)
        self.assertEqual((receipt["outcome"], receipt["attempts"]), ("failed", ["payload", "fallback"]))
        self.assertEqual(len(fake.state["posted"]), 2)

    def test_other_failures_are_not_retried(self):
        for status in (403, 429, 502, None):
            with self.subTest(status=status):
                fake = FakeGitHub(post_errors=[status])
                receipt = self.post(fake)
                self.assertEqual((receipt["outcome"], len(fake.state["posted"])), ("failed", 1))

    def test_read_back_mismatch_is_reported_without_reposting(self):
        fake = FakeGitHub()
        original = fake.create_review

        def drop_comment(payload):
            created = original(payload)
            fake.state["reviews"][-1]["comments"].pop()
            return created
        fake.create_review = drop_comment
        receipt = self.post(fake)
        self.assertEqual(receipt["outcome"], "mismatch")
        self.assertIn("review has 1 comments, expected 2", receipt["problems"])
        self.assertEqual(len(fake.state["posted"]), 1)

    def test_visibility_change_after_build_requires_a_new_build(self):
        receipt = self.post(FakeGitHub(), visibility="PUBLIC")
        self.assertEqual((receipt["outcome"], [r["code"] for r in receipt["reasons"]]), ("skipped", ["visibility"]))
        bundle, _ = self.bundle()
        bundle["visibility"] = "PUBLIC"
        with self.assertRaisesRegex(ValueError, "approved identity"):
            self.post(FakeGitHub(), bundle, self.bundle()[1])

    def test_ineligible_post_is_skipped_but_a_moved_head_is_allowed(self):
        pending = [rc.reason("pending", "pending draft")]
        receipt = self.post(FakeGitHub(), eligible=False, reasons=pending)
        self.assertEqual(receipt["outcome"], "skipped")
        moved = [rc.reason("head", "PR head moved")]
        receipt = self.post(FakeGitHub(), eligible=False, reasons=moved, head="c" * 40)
        self.assertEqual(receipt["outcome"], "posted")
        receipt = self.post(FakeGitHub(), reviewed_commit="e" * 40)
        self.assertEqual((receipt["outcome"], receipt["reasons"][0]["code"]), ("skipped", "commit"))


class CommandLineTests(unittest.TestCase):
    def test_out_directory_must_be_outside_the_whole_worktree_and_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["git", "init", "-q", temp], check=True, capture_output=True)
            (Path(temp) / "src").mkdir()
            for cwd, out in ((temp, "out"), (str(Path(temp) / "src"), str(Path(temp) / "private-post"))):
                with self.subTest(cwd=cwd), contextlib.chdir(cwd), \
                        contextlib.redirect_stderr(io.StringIO()) as stderr:
                    code = rc.main(["build", "--input", "in.json", "--context", "c.json", "--out", out])
                self.assertEqual(code, 2)
                self.assertIn("outside the reviewed worktree", stderr.getvalue())
                self.assertIn("The review result stands", stderr.getvalue())
                self.assertFalse(Path(out if Path(out).is_absolute() else Path(temp) / out).exists())
        with tempfile.TemporaryDirectory() as temp, contextlib.chdir(temp), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(rc.main(["build", "--input", "a", "--context", "b", "--out", "/nonexistent-x"]), 2)
        self.assertIn("The review result stands", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
