"""Check human audit output against replayed findings and isolated wiki files."""

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

import development_audit as audit
import development_audit_data as projection
import development_audit_render as rendering
import development_manifest as plan
import review_loop_state


def reviewed_fixture(*, extra_review_fixes=False, category_format="token", retry_failed_fix=False):
    ledger = {"schema": 1, "run_id": "a" * 32, "root": "/private/fixture",
              "objective": "Fixture", "scope": "Fixture", "base": "b" * 40,
              "limits": {"outer": 3 if extra_review_fixes else 2, "inner": 2}, "initial": "before",
              "snapshots": {"before": {}, "after": {}}, "events": []}
    snapshot = "before"

    def event(kind, **data):
        value = {"type": kind, "sequence": len(ledger["events"]) + 1, "snapshot": snapshot,
                 "actor": "PRIVATE-ACTOR", "reason": "PRIVATE-REASON", "time": "2026-11-24T12:00:00Z"}
        ledger["events"].append(value | data)

    def finding(number, category="documentation", severity="Low"):
        event("finding", key=f"PRIVATE-KEY-{number}", summary="PRIVATE-SUMMARY",
              severity=severity, locations=["/private/fixture/source.py:9"],
              evidence=[category_evidence(category)])

    def category_evidence(category):
        if category_format == "json":
            return json.dumps({"review_type": category, "details": "PRIVATE-EVIDENCE"})
        if category_format == "missing":
            return "PRIVATE-EVIDENCE"
        return f"review_type={category} PRIVATE-EVIDENCE"

    def decision(number, disposition, validation="valid", severity="Low"):
        event("decision", id=f"F{number:03}", validation=validation, disposition=disposition,
              severity=severity, evidence=["PRIVATE-DECISION"])

    passes = [{"name": name if category_format == "token" else f"Full {name} assessment",
               "worker": "unobserved", "result": "complete",
               "evidence": "PRIVATE-PASS" if category_format == "token" else category_evidence(name)}
              for name in ("correctness", "documentation")]
    checks = [{"name": "PRIVATE-CHECK", "result": "passed", "evidence": "PRIVATE-CHECK-EVIDENCE"}]
    event("start_review")
    for number in range(1, 7):
        finding(number, "correctness" if number == 2 else "documentation",
                "Medium" if number == 1 else "Low")
    event("review_done", passes=passes, checks=checks)
    for number, disposition, validation in (
            (1, "open", "valid"), (2, "out_of_scope", "valid"), (3, "ignored", "valid"),
            (4, "ignored", "invalid"), (5, "open", "valid"), (6, "ignored", "invalid")):
        decision(number, disposition, validation, "Medium" if number == 1 else "Low")
    event("start_fix", findings=["F001", "F005"], files=["source.py"])
    snapshot = "after"
    event("fix_done", results={name: {"result": "failed" if retry_failed_fix and name == "F001" else "applied",
                                    "evidence": "PRIVATE-FIX"}
                              for name in ("F001", "F005")}, checks=checks)
    event("fixes_reviewed", passes=passes)
    decision(1, "fix_failed" if retry_failed_fix else "fixed", severity="Medium")
    decision(5, "fixed")
    finding(7, "project:autonomous-continuation")
    decision(7, "ignored")
    event("advance")
    if retry_failed_fix:
        event("start_fix", findings=["F001"], files=["source.py"])
        event("fix_done", results={"F001": {"result": "applied", "evidence": "PRIVATE-FIX"}}, checks=checks)
        event("fixes_reviewed", passes=passes)
        decision(1, "fixed", severity="Medium")
        event("advance")
    event("start_review")
    event("review_done", passes=passes, checks=checks)
    finding(8)
    decision(8, "ignored", "invalid")
    if extra_review_fixes:
        finding(9)
        decision(9, "open")
        event("start_fix", findings=["F009"], files=["source.py"])
        event("fix_done", results={"F009": {"result": "applied", "evidence": "PRIVATE-FIX"}}, checks=checks)
        event("fixes_reviewed", passes=passes)
        finding(10)
        decision(10, "ignored")
        decision(9, "fixed")
        event("advance")
        event("start_review")
        event("review_done", passes=passes, checks=checks)
    event("advance")
    state = review_loop_state.replay(ledger)
    assert state["outcome"] == "completed_with_exceptions"
    phases, event_pass = projection.review_passes(ledger, state)
    record = {"id": ledger["run_id"], "available": True, "passes": phases,
              "findings": projection.review_findings(state, event_pass)}
    public = {
        "summary": "The change shipped with bounded, recorded exceptions.",
        "method": "Independent category reviews and adjudication.",
        "verification": [{"check": "Targeted tests", "result": "Passed", "runner": "implementer"},
                         {"check": "Manual check", "result": "Passed",
                          "runner": "run by hand after the run stopped"}],
        "not_verified": "Live host behavior.",
        "planning": {"model": "planning-model", "effort": "session default", "human_approved": True},
        "issues": ["https://github.com/fixture/project/issues/61"],
        "findings": [{
            "review": record["id"], "id": item["id"], "summary": f"Public report for {item['id']}.",
            "rationale": "Public explanation.", "key": f"documentation-pr-links-{number}",
            "locations": [f"source.py:{line}" for line in range(1, 6)],
            "decisions": [{"sequence": entry["sequence"],
                           "reason": ("Links were broken. Further detail." if index == 0
                                      else "The links now resolve. Checked all consumers.")}
                          for index, entry in enumerate(item["decisions"])],
            "tracking_issues": ["https://github.com/fixture/project/issues/71"] if number == 2 else [],
        } for number, item in enumerate(record["findings"], 1)],
        "regressions": [], "limitations": ["Offline fixture only."],
    }
    audit.public_narrative(public, [record])
    projection.add_public_findings([record], public)
    return {
        "schema": 2, "run": "c" * 32, "assignment": "A0010", "stage": "audit-final",
        "code_commit": "d" * 40, "reviews": [record], "public": public,
        "models": [{"role": "reviewer", "selected_model": "requested-review",
                    "selected_effort": "high", "actual_model": "actual-private-model"}],
        "requested_models": {
            "implement": [{"model": "implementation-model", "effort": "high"}],
            "fixer": [{"model": "implementation-model", "effort": "high"}],
            "prepare": [{"model": "setup-model", "effort": "medium"}],
        },
        "models_unavailable": False, "limitations": [],
        "publication": {"title": "Incremental delivery planning for autonomous development",
                        "pr_url": "https://github.com/fixture/project/pull/69",
                        "head": "d" * 40, "date": "2026-11-24"},
        "history": [{"id": "A0001", "role": "prepare", "attempt": 1, "outcome": "complete"},
                    {"id": "A0010", "role": "audit-final", "attempt": 1, "outcome": "reserved"}],
    }


class AuditFormatTests(unittest.TestCase):
    def setUp(self):
        self.bundle = reviewed_fixture()

    def test_outcome_counts_order_statuses_and_separators(self):
        report = audit.render(self.bundle).decode()
        self.assertNotRegex(report, r"(?m)^# ")
        self.assertTrue(report.startswith("Pull request: [#69](https://github.com/fixture/project/pull/69)"))
        self.assertIn("Issue: [#61]", report)
        self.assertIn("Published 2026-11-24 as a final audit", report)
        for label, count in (("Fixed", 2), ("Real but not fixed here", 1),
                             ("Accurate with no change needed", 2), ("Rejected", 3)):
            self.assertIn(f"| {label} | {count} |", report)
        self.assertIn("| **Total** | **8** |", report)
        headings = re.findall(r"(?m)^## (.+)", report)
        self.assertEqual(headings, ["Outcome", "How it was reviewed", "What was verified", "Known gaps",
                                    "Fixed (2)", "Real problems not fixed in this PR (1)",
                                    "Accurate observations, no change needed (2)", "Rejected (3)",
                                    "Process record", "Identifiers"])
        fixed = report.split("## Fixed (2)")[1].split("## Real problems")[0]
        self.assertLess(fixed.index("Finding 1:"), fixed.index("Finding 5:"))
        self.assertEqual(fixed.count("\n---\n"), 1)
        self.assertNotIn("\n---\n", fixed.split("#### Finding")[0])
        self.assertIn("**Confirmed, fixed** &#183; medium impact", fixed)
        self.assertIn("Initial decision: Confirmed, to be fixed.", fixed)
        self.assertIn("Then: Confirmed, fixed.", fixed)
        self.assertIn("**Why it mattered:** Links were broken.", fixed)
        self.assertIn("**How it was fixed:** The links now resolve.", fixed)
        self.assertNotIn("**How it was fixed:** The links now resolve. Checked", fixed)
        self.assertIn("`source.py:4` and more", fixed)
        self.assertNotIn("`source.py:5`", fixed)
        self.assertIn("**Confirmed, outside this PR**", report)
        self.assertIn("tracked in [#71](https://github.com/fixture/project/issues/71)", report)
        self.assertIn("**Confirmed, no change needed**", report)
        rejected = report.split("## Rejected (3)")[1].split("## Process record")[0]
        self.assertIn("<details><summary>Show all rejected findings</summary>", rejected)
        self.assertEqual(rejected.count("**Rejected, not a defect**"), 3)
        self.assertEqual(rejected.count("\n---\n"), 2)
        self.assertNotIn("**Where:**", rejected)

    def test_passes_models_checks_and_identifier_boundary(self):
        report = audit.render(self.bundle).decode()
        for row in ("| First review | 2 recorded category passes | 6 findings assessed; 2 to fix |",
                    "| Fix cycle | Fixer assigned 2 corrections | 2 applied; 0 failed |",
                    "| Check of the fixes | 2 recorded category passes | 3 findings assessed; 0 to fix |",
                    "| Second review | 2 recorded category passes | 1 finding assessed; 0 to fix |"):
            self.assertIn(row, report)
        self.assertIn("| Planning and design | Prepare in the launching session, before the run; human approval recorded | planning-model | session default |", report)
        self.assertIn("| Implementation and fixes | Implementer, Fixer | implementation-model | high |", report)
        self.assertIn("| Setup and delivery | Worktree and branch setup (prepare) | setup-model | medium |", report)
        self.assertIn("| Review and judgment | Category reviewers | requested-review | high |", report)
        self.assertNotIn("actual-private-model", report)
        self.assertIn("Setup and delivery roles make no design decisions", report)
        self.assertIn("requested models, not observed identities", report)
        self.assertIn("| Fix cycle recorded checks | 1 passed (fixer) |", report)
        self.assertIn("| Targeted tests | Passed (implementer) |", report)
        self.assertIn("run by hand after the run stopped", report)
        self.assertIn("Not verified: Live host behavior.", report)
        above, identifiers = report.split("## Identifiers")
        self.assertNotRegex(above, r"[a-f0-9]{32,}")
        for value in (self.bundle["run"], self.bundle["code_commit"], self.bundle["reviews"][0]["id"]):
            self.assertIn(value, identifiers)
        self.assertIn(plan.digest(plan.encode(self.bundle)), identifiers)
        self.assertNotIn("PRIVATE-", json.dumps(self.bundle))

    def test_structured_details_include_rejected_and_no_action_findings(self):
        for item in self.bundle["reviews"][0]["findings"]:
            with self.subTest(finding=item["id"]):
                self.assertTrue(item["reason"])
                self.assertEqual(len(item["locations"]), 5)
                expected = {"F002": "correctness", "F007": "project:autonomous-continuation"}
                self.assertEqual(item["category"], [expected.get(item["id"], "documentation")])
                self.assertTrue(item["pass"])
                self.assertTrue(item["details_available"])
                self.assertEqual(len(item["decisions"]), len(item["observations"]) + (item["id"] in {"F001", "F005"}))
        items = self.bundle["reviews"][0]["findings"]
        self.assertEqual(items[6]["pass"], "Check of the fixes")
        self.assertEqual(items[7]["pass"], "Second review")

    def test_json_category_evidence_survives_ledger_projection_and_missing_evidence_stays_unknown(self):
        for encoding in ("json", "missing"):
            with self.subTest(encoding=encoding):
                bundle = reviewed_fixture(category_format=encoding)
                record = bundle["reviews"][0]
                for item in record["findings"]:
                    category = {"F002": "correctness", "F007": "project:autonomous-continuation"}.get(
                        item["id"], "documentation")
                    self.assertEqual(item["category"], [category] if encoding == "json" else [])
                for phase in record["passes"]:
                    expected = ["correctness", "documentation"] if phase["kind"] == "review" else []
                    self.assertEqual(phase["categories"], expected if encoding == "json" else [])
                report = audit.contents(bundle)
                exported = json.loads(report["audit.json"])
                self.assertEqual(exported["reviews"][0]["findings"], record["findings"])
                if encoding == "json":
                    self.assertIn("2 recorded category passes", report["AUDIT.md"].decode())
                    self.assertNotIn("Category unavailable", report["AUDIT.md"].decode())
                else:
                    self.assertIn("0 recorded category passes", report["AUDIT.md"].decode())
                    self.assertIn("Category unavailable", report["AUDIT.md"].decode())
                self.assertNotIn("PRIVATE-EVIDENCE", report["audit.json"].decode())

    def test_category_metadata_ignores_unrecognized_and_nested_values(self):
        categories = {"correctness", "integration"}
        for evidence in ('{"review_type":', '{"review_type":[]}', '{"review_type":null}',
                         '{"review_type":"unknown"}', '["integration"]',
                         '{"details":{"review_type":"integration"}}'):
            with self.subTest(evidence=evidence):
                self.assertEqual(projection.evidence_categories(evidence, categories), set())
        self.assertEqual(projection.evidence_categories(
            'review_type=correctness review_type=integration review_type=correctness', categories),
            {"correctness", "integration"})

    def test_category_tokens_do_not_credit_identifier_prefixes(self):
        categories = {"correctness", "integration"}
        for suffix in ("_extra", ".extra", "/extra", ",", '"'):
            with self.subTest(suffix=suffix):
                evidence = f"review_type=correctness{suffix} review_type=project:recovery{suffix}"
                self.assertEqual(projection.evidence_categories(evidence, categories), set())
        self.assertEqual(projection.evidence_categories(
            "review_type=correctness\nreview_type=project:recovery\t review_type=integration", categories),
            {"correctness", "project:recovery", "integration"})

    def test_partial_model_observations_keep_all_saved_requests(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["requested_models"]["reviewer"] = [
            {"model": "requested-review", "effort": "high"},
            {"model": "retry-review", "effort": "medium"},
        ]
        report = audit.render(bundle).decode()
        self.assertEqual(report.count(
            "| Review and judgment | Category reviewers | requested-review | high |"), 1)
        self.assertIn("| Review and judgment | Category reviewers | retry-review | medium |", report)
        self.assertNotIn("actual-private-model", report)
        bundle["models"][0].update(selected_model=None, selected_effort=None)
        rows = rendering.model_rows(bundle)
        self.assertIn(["Review and judgment", "Category reviewers", "requested-review", "high"], rows)
        self.assertIn(["Review and judgment", "Category reviewers", "retry-review", "medium"], rows)

    def test_requested_models_use_scoped_saved_jobs_not_configuration_or_private_fields(self):
        state = {
            "history": [{"id": "A1", "pr": None}, {"id": "A2", "pr": "first"},
                        {"id": "A3", "pr": "other"}],
            "handoffs": {
                "B1": {"assignment": "A1", "spec": {"jobs": [
                    {"role": "preflight", "options": {}, "prompt": "PRIVATE-PROMPT"}]}},
                "B2": {"assignment": "A2", "spec": {"jobs": [
                    {"role": "reviewer", "options": {"model": "requested", "effort": "high"}},
                    {"role": "reviewer", "options": {"model": "requested", "effort": "high"}},
                    {"role": "validator", "options": {"effort": "medium"}},
                    {"role": "fixer"}]}},
                "B3": {"assignment": "A2", "spec": {"jobs": [
                    {"role": "reviewer", "options": {}}]}},
                "B4": {"assignment": "A3", "spec": {"jobs": [
                    {"role": "reviewer", "options": {"model": "PRIVATE-OTHER-PR"}}]}},
            },
        }
        expected = {"preflight": [{"model": None, "effort": None}],
                    "reviewer": [{"model": "requested", "effort": "high"}, {"model": None, "effort": None}],
                    "validator": [{"model": None, "effort": "medium"}]}
        self.assertEqual(projection.requested_models(state, "first"), expected)
        state.pop("handoffs")
        self.assertEqual(projection.requested_models(state, "first"), {})

    def test_impact_category_and_number_break_sorting_ties(self):
        items = rendering.findings(self.bundle)
        fixed = [item for item in items if item["id"] in ("F001", "F005")]
        fixed[1]["severity"] = "High"
        report = "\n".join(rendering.finding_sections(fixed, "fixture/project"))
        self.assertLess(report.index("Finding 5:"), report.index("Finding 1:"))
        fixed[0]["severity"] = fixed[1]["severity"] = "Low"
        fixed[0]["category"] = ["privacy"]
        fixed[1]["category"] = ["documentation"]
        report = "\n".join(rendering.finding_sections(fixed, "fixture/project"))
        self.assertLess(report.index("Finding 5:"), report.index("Finding 1:"))
        fixed[0]["category"] = ["documentation"]
        report = "\n".join(rendering.finding_sections(list(reversed(fixed)), "fixture/project"))
        self.assertLess(report.index("Finding 1:"), report.index("Finding 5:"))

    def test_later_fix_reviews_keep_distinct_pass_names(self):
        bundle = reviewed_fixture(extra_review_fixes=True)
        report = audit.render(bundle).decode()
        self.assertIn("| Fix cycle (review 2) |", report)
        self.assertIn("| Check of the fixes (review 2) |", report)
        self.assertIn("| Review pass 3 |", report)
        self.assertEqual(bundle["reviews"][0]["findings"][-1]["pass"], "Check of the fixes (review 2)")

    def test_failed_corrections_remain_to_fix_until_a_successful_retry(self):
        bundle = reviewed_fixture(retry_failed_fix=True)
        report = audit.render(bundle).decode()
        self.assertIn("| Fix cycle | Fixer assigned 2 corrections | 1 applied; 1 failed |", report)
        self.assertIn("| Check of the fixes | 2 recorded category passes | 3 findings assessed; 1 to fix |", report)
        self.assertIn("| Fix cycle 2 | Fixer assigned 1 correction | 1 applied; 0 failed |", report)
        self.assertIn("| Check of the fixes 2 | 2 recorded category passes | 1 finding assessed; 0 to fix |", report)

    def test_multiple_ledgers_have_distinct_display_numbers_and_regression_references(self):
        bundle = copy.deepcopy(self.bundle)
        second = copy.deepcopy(bundle["reviews"][0])
        second["id"] = "e" * 32
        second["findings"] = second["findings"][:1]
        bundle["reviews"].append(second)
        bundle["public"]["regressions"] = [{
            "cause": {"review": bundle["reviews"][0]["id"], "id": "F001"},
            "effect": {"review": second["id"], "id": "F001"},
            "basis": "observed", "evidence": "Public evidence",
        }]
        report = audit.render(bundle).decode()
        self.assertEqual(report.count("#### Finding 1:"), 1)
        self.assertEqual(report.count("#### Finding 9:"), 1)
        self.assertIn("Finding 1 to finding 9 (observed)", report)
        self.assertIn("| Review 2: First review |", report)
        self.assertIn(f"`{second['id']}` (findings 9)", report)

    def test_partial_passes_failed_checks_and_pending_decisions_remain_visible(self):
        bundle = copy.deepcopy(self.bundle)
        phases = bundle["reviews"][0]["passes"]
        phases[0].update(complete=False, settled=False)
        phases[1].update(complete=False, checks=["failed", "unavailable"])
        phases[2].update(settled=False, invalidated=True)
        bundle["reviews"][0]["findings"][0]["decisions"] = []
        bundle["reviews"][0]["findings"][0].update(validation="pending", disposition="open")
        report = audit.render(bundle).decode()
        self.assertIn("Review started; completion not recorded", report)
        self.assertIn("Incomplete; no fix result recorded", report)
        self.assertIn("adjudication completion not recorded; superseded after reconciliation", report)
        self.assertIn("| Fix cycle recorded checks | 1 failed, 1 unavailable (fixer) |", report)
        self.assertIn("No adjudication decision was recorded.", report)
        bundle["public"]["planning"] = {"model": None, "effort": None, "human_approved": False}
        bundle["models"] = []
        bundle["requested_models"]["fixer"].append({"model": "retry-model", "effort": "medium"})
        rows = rendering.model_rows(bundle)
        self.assertEqual(rows[0][-2:], ["Not recorded", "Not recorded"])
        self.assertIn(["Implementation and fixes", "Fixer", "retry-model", "medium"], rows)

    def test_legacy_narrative_keeps_public_rationale_without_copying_private_details(self):
        public = copy.deepcopy(self.bundle["public"])
        for item in public["findings"]:
            for key in ("key", "locations", "decisions", "tracking_issues"):
                del item[key]
        records = copy.deepcopy(self.bundle["reviews"])
        audit.public_narrative(public, records)
        projection.add_public_findings(records, public)
        report = audit.render({**self.bundle, "public": public, "reviews": records}).decode()
        self.assertIn("Legacy narrative lacks structured public finding details", report)
        self.assertIn("Public decision reason not supplied.", report)
        self.assertEqual(records[0]["findings"][3]["reason"], "Public explanation.")
        self.assertEqual(records[0]["findings"][3]["locations"], [])
        self.assertNotIn("PRIVATE-", report)

    def test_invalid_public_details_fail_before_output(self):
        public = self.bundle["public"]
        mutations = [
            ("missing decisions", lambda value: value["findings"][0]["decisions"].clear()),
            ("unknown decision", lambda value: value["findings"][0]["decisions"][0].update(sequence=999)),
            ("private path", lambda value: value["findings"][0].update(locations=["/private/run/source.py"])),
            ("traversal", lambda value: value["findings"][0].update(locations=["../private/source.py"])),
            ("Windows path", lambda value: value["findings"][0].update(locations=["C:\\private\\source.py:1"])),
            ("bad issue", lambda value: value["findings"][0].update(tracking_issues=["javascript:alert(1)"])),
            ("missing runner", lambda value: value["verification"][0].pop("runner")),
            ("implicit approval", lambda value: value["planning"].update(human_approved="yes")),
            ("empty title", lambda value: value["findings"][0].update(key="documentation-")),
        ]
        for label, mutate in mutations:
            with self.subTest(case=label):
                changed = copy.deepcopy(public)
                mutate(changed)
                with self.assertRaises(plan.ManifestError):
                    audit.public_narrative(changed, self.bundle["reviews"])

    def test_unresolved_and_missing_evidence_never_claim_fixed_or_clean(self):
        for validation, disposition, expected in (
                ("valid", "open", "Confirmed, to be fixed"),
                ("valid", "fix_applied", "Confirmed, fix awaiting verification"),
                ("valid", "fix_failed", "Confirmed, fix failed"),
                ("pending", "open", "Not yet assessed"),
                ("uncertain", "ignored", "Uncertain, needs assessment")):
            with self.subTest(state=(validation, disposition)):
                bundle = copy.deepcopy(self.bundle)
                bundle["reviews"][0]["findings"] = [bundle["reviews"][0]["findings"][0]]
                bundle["reviews"][0]["findings"][0].update(validation=validation, disposition=disposition)
                report = audit.render(bundle).decode()
                self.assertIn("| Fixed | 0 |", report)
                self.assertIn(f"**{expected}**", report)
                if validation != "valid":
                    self.assertIn("## Unresolved findings (1)", report)
                else:
                    self.assertIn("| Real but not fixed here | 1 |", report)
                    self.assertIn("| Accurate with no change needed | 0 |", report)
                    self.assertIn("## Real problems not fixed in this PR (1)", report)
                    unfixed = report.split("## Real problems not fixed in this PR (1)")[1].split(
                        "## Accurate observations, no change needed")[0]
                    self.assertIn("#### Finding 1:", unfixed)
        bundle = copy.deepcopy(self.bundle)
        bundle["reviews"] = [{"id": "e" * 32, "available": False}]
        bundle["models_unavailable"] = True
        bundle["public"].pop("planning")
        bundle["public"]["verification"] = "Legacy checks."
        bundle["publication"]["head"] = "f" * 40
        report = audit.render(bundle).decode()
        self.assertIn("| **Total** | **0** |", report)
        self.assertIn("their findings and counters were not reconstructed", report)
        self.assertIn("Some model records are unavailable", report)
        self.assertIn("approval not recorded", report)
        self.assertIn("runner not recorded", report)
        self.assertIn("Commit mismatch:", report)

    def test_text_cannot_create_headings_tables_or_html_and_regressions_use_display_numbers(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["public"]["summary"] = "# Injected\n<script>alert(1)</script> | fake"
        bundle["public"]["regressions"] = [{
            "cause": {"review": bundle["reviews"][0]["id"], "id": "F001"},
            "effect": {"review": bundle["reviews"][0]["id"], "id": "F007"},
            "basis": "inferred", "evidence": "Public evidence",
        }]
        report = audit.render(bundle).decode()
        self.assertIn(r"\# Injected &lt;script&gt;alert(1)&lt;/script&gt; \| fake", report)
        self.assertIn("Finding 1 to finding 7 (inferred): Public evidence", report)
        self.assertNotRegex(report, r"(?m)^# ")
        self.assertEqual(rendering.code("source`name.py:1"), "`` source`name.py:1 ``")

    def test_narrative_tildes_cannot_consume_the_outcome_table(self):
        for summary, escaped in (("~~~", r"\~\~\~"), ("~~~~ python", r"\~\~\~\~ python"),
                                 ("~~~\nexample", r"\~\~\~ example")):
            with self.subTest(summary=summary):
                bundle = copy.deepcopy(self.bundle)
                bundle["public"]["summary"] = summary
                audit.public_narrative(bundle["public"], bundle["reviews"])
                report = audit.contents(bundle)["AUDIT.md"].decode()
                self.assertIn(f"## Outcome\n\n{escaped}\n\n| Result | Findings | Meaning |", report)
                self.assertNotRegex(report, r"(?m)^ {0,3}~{3,}")

    def test_human_page_name_encodes_fragments_and_preserves_literal_hyphens(self):
        state = {"manifest": {"repository": {"url": "https://github.com/fixture/project.git"}},
                 "prs": {"first": {"url": "https://github.com/fixture/project/pull/69"}}}
        result = audit.publication_links(state, {"pr": "first"}, self.bundle["publication"]["title"])
        self.assertEqual(result["page"], "Audit:-PR-#69,-incremental-delivery-planning-for-autonomous-development")
        self.assertEqual(result["url"], "https://github.com/fixture/project/wiki/Audit:-PR-%2369,-incremental-delivery-planning-for-autonomous-development")
        self.assertEqual(urlsplit(result["url"]).fragment, "")
        self.assertEqual(unquote(result["url"].rsplit("/", 1)[1]), result["page"])
        page = audit.page_name("69", "PR-safe: parser / names #2 (new) ?")
        self.assertIn("PR" + chr(0x2010) + "safe:", page)
        self.assertNotIn("/", page)
        self.assertLess(len(audit.page_name("69", "word " * 100).encode()), 240)
        with self.assertRaises(plan.ManifestError):
            audit.page_name("69", "///")

    def test_archive_metadata_does_not_project_private_goals_or_unvalidated_links(self):
        state = {"manifest": {"repository": {"url": "https://github.com/fixture/project.git"},
                              "prs": [{"goal": "PRIVATE-GOAL"}]},
                 "prs": {"first": {"url": "https://private.invalid/PRIVATE-URL"}}}
        metadata = audit.default_publication(state, {"pr": "first"})
        self.assertIsNone(metadata["pr_url"])
        self.assertNotIn("PRIVATE", json.dumps(metadata))
        bundle = {**self.bundle, "publication": metadata, "stage": "archive"}
        report = audit.render(bundle).decode()
        self.assertTrue(report.startswith("Pull request: Not recorded"))
        self.assertIn("as a historical export", report)
        self.assertIn("PR head at publication: Not observed", report)

    def test_new_link_block_roundtrips_and_replaces_legacy_links(self):
        publication = {"url": "https://github.com/fixture/project/wiki/Audit:-PR-%2369,-readable",
                       "data_url": "https://github.com/fixture/project/wiki/Audit:-PR-%2369,-readable.json",
                       "index_url": "https://github.com/fixture/project/wiki/Automated-Pull-Request-Audits"}
        legacy = {**publication, "url": "https://github.com/fixture/project/wiki/Audit-PR-69-old",
                  "data_url": "https://github.com/fixture/project/wiki/Audit-PR-69-old.json"}
        body = "Human notes\n\n## Checklist\n- [ ] Keep me\n"
        previous = audit.pr_body(body, legacy)
        current = audit.pr_body(previous, publication)
        self.assertNotIn("Audit-PR-69-old", current)
        self.assertEqual(audit.pr_body(current, publication), current)
        self.assertIn("Human notes", current)
        self.assertTrue(current.endswith("## Checklist\n- [ ] Keep me\n"))

    def test_wiki_replacement_refuses_partial_foreign_and_symlinked_pages_then_recovers(self):
        state = {"manifest": {"repository": {"url": "https://github.com/fixture/project.git"}},
                 "prs": {"first": {"url": "https://github.com/fixture/project/pull/69"}}}
        publication = audit.publication_links(state, {"pr": "first"}, self.bundle["publication"]["title"])
        publication.update(title=self.bundle["publication"]["title"], date="2026-11-24")
        files = audit.contents(self.bundle)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / (publication["page"] + ".md")
            data = root / (publication["page"] + ".json")
            report.write_bytes(files["AUDIT.md"])
            with self.assertRaisesRegex(plan.ManifestError, "matching report/data pair"):
                audit.wiki_files(root, publication, files)
            legacy = {"schema": 1, "stage": "audit-final", "run": "a" * 32}
            data.write_bytes(plan.encode(legacy))
            with self.assertRaisesRegex(plan.ManifestError, "ownership metadata"):
                audit.wiki_files(root, publication, files)
            self.assertEqual(data.read_bytes(), plan.encode(legacy))
            self.assertEqual(report.read_bytes(), files["AUDIT.md"])
            foreign = copy.deepcopy(self.bundle)
            foreign["publication"]["pr_url"] = "https://github.com/other/repository/pull/69"
            data.write_bytes(plan.encode(foreign))
            with self.assertRaisesRegex(plan.ManifestError, "another PR"):
                audit.wiki_files(root, publication, files)
            data.write_bytes(files["audit.json"])
            report.unlink()
            report.symlink_to(data)
            with self.assertRaises(ValueError):
                audit.wiki_files(root, publication, files)
            report.unlink()
            report.write_bytes(files["AUDIT.md"])
            expected = audit.wiki_files(root, publication, files)
            self.assertEqual(expected[report.name], files["AUDIT.md"])
            self.assertEqual(expected[data.name], files["audit.json"])

    def test_identical_republish_keeps_index_order_but_changed_bytes_move_row_to_top(self):
        state = {"manifest": {"repository": {"url": "https://github.com/fixture/project.git"}},
                 "prs": {"first": {"url": "https://github.com/fixture/project/pull/69"}}}
        publication = audit.publication_links(state, {"pr": "first"}, "Readable audit")
        publication.update(title="Readable audit", date="2026-11-24")
        files = audit.contents(self.bundle)
        other = "| 2026-11-24 | [#2 Other](https://github.com/fixture/project/pull/2) | Other audit |\n"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, data in audit.wiki_files(root, publication, files).items():
                (root / name).write_bytes(data)
            index = root / (audit.INDEX_PAGE + ".md")
            text = index.read_text().replace(audit.INDEX_SEPARATOR + "\n", audit.INDEX_SEPARATOR + "\n" + other)
            index.write_text(text)
            self.assertEqual(audit.wiki_files(root, publication, files)[index.name].decode(), text)
            changed = copy.deepcopy(self.bundle)
            changed["public"]["summary"] = "Updated audit."
            expected = audit.wiki_files(root, publication, audit.contents(changed))[index.name].decode()
            self.assertLess(expected.index("/pull/69)"), expected.index("/pull/2)"))
            self.assertEqual(expected.count("[#69 "), 1)


if __name__ == "__main__":
    unittest.main()
