"""Regressions for the best-of-K clobber found in VARIANCE_ANALYSIS.md.

K concurrent attempts used to be told to write the same absolute deliverable path, so
they overwrote each other and the gate scored whichever file landed last. Each attempt
now writes in its own workdir and only the winner is published.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import execute as ex  # noqa: E402


class FakeLedger:
    def __init__(self, tmp):
        self.dir = Path(tmp)
        self.events = []

    def event(self, kind, **kw):
        self.events.append(dict(kind=kind, **kw))


def part(root):
    return {"id": "core", "title": "core", "contract": "c",
            "deliverables": [{"path": str(root / "solution.py"), "min_bytes": 10},
                             {"path": str(root / "tests" / "t.py"), "min_bytes": 1}],
            "verify_cmd": "python3 -c 'import solution'"}


class IsolateTest(unittest.TestCase):
    def test_paths_move_into_the_attempt_workdir(self):
        with tempfile.TemporaryDirectory() as td:
            root, att = Path(td) / "work", Path(td) / "parts/core/a1-lane"
            cloned = ex.isolate_part(part(root), att)
            paths = [d["path"] for d in cloned["deliverables"]]
            self.assertEqual(paths, [str(att / "solution.py"), str(att / "t.py")])

    def test_original_part_is_not_mutated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "work"
            original = part(root)
            before = [d["path"] for d in original["deliverables"]]
            ex.isolate_part(original, Path(td) / "other")
            self.assertEqual([d["path"] for d in original["deliverables"]], before)

    def test_two_attempts_do_not_share_a_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "work"
            a1 = ex.isolate_part(part(root), Path(td) / "a1")
            a2 = ex.isolate_part(part(root), Path(td) / "a2")
            self.assertNotEqual([d["path"] for d in a1["deliverables"]],
                                [d["path"] for d in a2["deliverables"]])

    def test_min_bytes_survives_the_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            cloned = ex.isolate_part(part(Path(td)), Path(td) / "a1")
            self.assertEqual(cloned["deliverables"][0]["min_bytes"], 10)


class PublishTest(unittest.TestCase):
    def test_winner_is_copied_to_the_canonical_path(self):
        with tempfile.TemporaryDirectory() as td:
            root, att = Path(td) / "work", Path(td) / "a1"
            (att).mkdir(parents=True)
            (att / "solution.py").write_text("print('winner')\n" * 10, encoding="utf-8")
            ledger = FakeLedger(td)
            moved = ex.publish_part(ex.isolate_part(part(root), att), part(root),
                                    ledger, "core")
            self.assertEqual(len(moved), 1)
            self.assertTrue((root / "solution.py").exists())
            self.assertIn("winner", (root / "solution.py").read_text(encoding="utf-8"))
            gates = [e for e in ledger.events if e["kind"] == "gate"]
            self.assertTrue(gates and gates[0]["stage"] == "publish.core")

    def test_missing_attempt_file_is_not_published_over(self):
        with tempfile.TemporaryDirectory() as td:
            root, att = Path(td) / "work", Path(td) / "a1"
            att.mkdir(parents=True)
            ledger = FakeLedger(td)
            self.assertEqual(ex.publish_part(ex.isolate_part(part(root), att),
                                             part(root), ledger, "core"), [])

    def test_publish_failure_is_recorded_not_raised(self):
        with tempfile.TemporaryDirectory() as td:
            root, att = Path(td) / "work", Path(td) / "a1"
            att.mkdir(parents=True)
            (att / "solution.py").write_text("x" * 50, encoding="utf-8")
            (root / "solution.py").mkdir(parents=True)   # a directory where a file belongs
            ledger = FakeLedger(td)
            moved = ex.publish_part(ex.isolate_part(part(root), att), part(root),
                                    ledger, "core")
            self.assertEqual(moved, [])
            self.assertTrue([e for e in ledger.events if e["kind"] == "warning"])


def attempt(lane_id, checks, bytes_, reply):
    return {"lane": SimpleNamespace(id=lane_id),
            "checks": checks, "receipts": [SimpleNamespace(bytes=bytes_)],
            "result": SimpleNamespace(text=reply)}


class LeastBadTest(unittest.TestCase):
    def test_artefacts_beat_narration(self):
        talker = attempt("loud", [], 0, "Let me rewrite. " * 200)
        worker = attempt("quiet", [], 4000, "")
        self.assertEqual(ex._least_bad([talker, worker])["lane"].id, "quiet")

    def test_passing_checks_outrank_raw_size(self):
        big = attempt("big", [{"passed": False}], 9000, "")
        small = attempt("small", [{"passed": True}, {"passed": True}], 300, "")
        self.assertEqual(ex._least_bad([big, small])["lane"].id, "small")

    def test_counts_are_robust_to_junk(self):
        att = attempt("x", ["not-a-dict", {"passed": True}, None], "not-an-int", "")
        self.assertEqual(ex._check_pass_count(att), 1)
        self.assertEqual(ex._receipt_bytes(att), 0)


if __name__ == "__main__":
    unittest.main()
