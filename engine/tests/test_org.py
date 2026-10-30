"""Routing regressions: the same task must reach the same department, and a chain
without a real file on disk must never be reported as verified."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import org as org_mod  # noqa: E402

KITS = Path("/home/ubuntu/aaryas-life/organisation-rebuild/departments")

CASES = [
    ("Draft a thank-you note after meeting my research advisor", "personal"),
    ("Make a Diwali invitation poster and render a preview PNG", "design"),
    ("Fix the off-by-one in the CSV loader and add a unit test", "engineering"),
    ("Find 3 new sponsor prospects with verified contacts and draft first-touch emails",
     "outreach"),
    ("Run the Sunday relationship sweep and draft what is due", "personal"),
    ("Write a decision memo comparing two storage options with trade-offs", "research"),
    ("Announce the workshop to club members, draft only", "club"),
]


@unittest.skipUnless(KITS.is_dir(), "staged kits not present")
class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.org = org_mod.Org(KITS)

    def test_each_task_reaches_its_department(self):
        for text, want in CASES:
            with self.subTest(task=text[:40]):
                self.assertEqual(self.org.classify(text)[0]["department"], want)

    def test_routing_is_deterministic(self):
        text = CASES[2][0]
        self.assertEqual(self.org.classify(text)[0]["department"],
                         self.org.classify(text)[0]["department"])

    def test_unroutable_task_raises_instead_of_guessing(self):
        with self.assertRaises(org_mod.RoutingError):
            self.org.classify("??? !!!")

    def test_a_pinned_department_overrides_the_score(self):
        plan = self.org.plan(CASES[0][0], department="club")
        self.assertEqual(plan["department"], "club")
        self.assertIn("pinned", " ".join(plan["rationale"]))

    def test_plan_names_an_agent_from_the_kit(self):
        plan = self.org.plan(CASES[4][0])
        self.assertEqual(plan["agent"]["name"], "personal-1")
        self.assertEqual(len(plan["agent"]["id"]), 36)

    def test_depth_comes_from_the_kit_not_a_default(self):
        plan = self.org.plan("Write a decision memo with options and trade-offs")
        self.assertEqual(plan["depth"], self.org.profiles()["research"].agent_depth(
            plan["agent"]["name"]))

    def test_support_hops_are_capped(self):
        plan = self.org.plan("Build the site, design the poster, research sponsors and "
                             "write the announcement for the club event")
        self.assertLessEqual(len(plan["supports"]), org_mod.MAX_SUPPORTS)

    def test_chain_description_carries_the_never_list(self):
        plan = self.org.plan(CASES[0][0])
        text = self.org.chain_description(plan)
        self.assertIn("CEO routing decision", text)
        self.assertIn("Must never happen", text)
        for line in plan["never"][:1]:
            self.assertIn(line.split()[0], text)


class IssueIdTest(unittest.TestCase):
    def test_uuid_is_preferred(self):
        uid = "6f2d1a44-0b8e-4f3a-9c21-77aa55bb1122"
        self.assertEqual(org_mod.Org._issue_id(f"id={uid} name=x"), uid)

    def test_identifier_is_accepted(self):
        self.assertEqual(org_mod.Org._issue_id("created AAR-193 ok"), "AAR-193")

    def test_nothing_found_is_empty_not_wrong(self):
        self.assertEqual(org_mod.Org._issue_id("no identifier here"), "")


class VerifyTest(unittest.TestCase):
    def test_a_child_without_a_file_is_never_verified(self):
        org = org_mod.Org(KITS)
        org.status = lambda issue: {"issue": issue, "ok": True, "status": "done",
                                   "detail": "still working, heartbeat updated"}
        verdict = org.verify({"children": [{"issue": "AAR-1", "department": "design"}]})
        self.assertFalse(verdict["verified"])
        self.assertTrue(any("heartbeat" in p for p in verdict["problems"]))

    def test_a_real_receipt_on_disk_passes(self):
        org = org_mod.Org(KITS)
        with tempfile.TemporaryDirectory() as td:
            receipt = Path(td) / "RECEIPT.md"
            receipt.write_text("# Receipt\n" + "evidence " * 40, encoding="utf-8")
            org.status = lambda issue: {"issue": issue, "ok": True, "status": "done",
                                       "detail": f"DONE file at {receipt}"}
            verdict = org.verify({"children": [{"issue": "AAR-2", "department": "club"}]})
            self.assertTrue(verdict["verified"], verdict["problems"])

    def test_a_still_open_child_blocks_the_chain(self):
        org = org_mod.Org(KITS)
        with tempfile.TemporaryDirectory() as td:
            receipt = Path(td) / "R.md"
            receipt.write_text("x" * 400, encoding="utf-8")
            org.status = lambda issue: {"issue": issue, "ok": True, "status": "in_progress",
                                        "detail": f"at {receipt}"}
            verdict = org.verify({"children": [{"issue": "AAR-3", "department": "club"}]})
            self.assertFalse(verdict["verified"])

    def test_an_empty_file_is_not_a_receipt(self):
        org = org_mod.Org(KITS)
        with tempfile.TemporaryDirectory() as td:
            receipt = Path(td) / "R.md"
            receipt.write_text("done", encoding="utf-8")
            org.status = lambda issue: {"issue": issue, "ok": True, "status": "done",
                                       "detail": f"at {receipt}"}
            self.assertFalse(org.verify(
                {"children": [{"issue": "AAR-4", "department": "club"}]})["verified"])


class DispatchTest(unittest.TestCase):
    def test_dry_run_creates_nothing(self):
        org = org_mod.Org(KITS)
        calls = []
        org._cli = lambda *a: calls.append(a) or _Empty()
        result = org.dispatch(org.plan(CASES[1][0]), dry_run=True)
        self.assertEqual(calls, [])
        self.assertTrue(result["dry_run"])
        self.assertIsNone(result["parent"])
        self.assertTrue(result["would_create"])

    def test_titling_strips_words_that_route_to_a_paid_tier(self):
        org = org_mod.Org(KITS)
        result = org.dispatch(org.plan("Make this architecture heavy and complex, "
                                       "the [max] version"), dry_run=True)
        for item in result["would_create"]:
            for banned in ("max", "heavy", "complex", "architecture"):
                self.assertNotIn(banned, item["title"].lower())


class _Empty:
    returncode = 0
    stdout = ""
    stderr = ""


if __name__ == "__main__":
    unittest.main()
