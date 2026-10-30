"""Tests for promise_log.py. Every test uses a temp store; the live store is never touched."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import promise_log as pl  # noqa: E402


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = str(Path(self.tmp.name) / "promises.json")

    def call(self, args):
        return pl.main(["--store", self.store, *args])

    def entries(self):
        path = Path(self.store)
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))


class AddTest(Store):
    def test_add_creates_a_record(self):
        self.assertEqual(self.call(["add", "--person", "asha-verma",
                                    "--text", "send the draft", "--today", "2026-11-01"]), 0)
        one = self.entries()
        self.assertEqual(len(one), 1)
        self.assertEqual(one[0]["person"], "asha-verma")
        self.assertEqual(one[0]["made"], "2026-11-01")
        self.assertEqual(one[0]["status"], "open")

    def test_id_is_deterministic(self):
        a = pl.make_id("asha-verma", "2026-11-01", "send the draft")
        b = pl.make_id("asha-verma", "2026-11-01", "send the draft")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 8)

    def test_duplicate_add_returns_four_and_stores_once(self):
        args = ["add", "--person", "rohit-nanda", "--text", "ask about the move"]
        self.assertEqual(self.call(args + ["--today", "2026-11-01"]), 0)
        self.assertEqual(self.call(args + ["--today", "2026-11-01"]), 4)
        self.assertEqual(len(self.entries()), 1)

    def test_same_text_different_day_is_a_new_promise(self):
        self.call(["add", "--person", "rohit", "--text", "call back", "--today", "2026-11-01"])
        self.call(["add", "--person", "rohit", "--text", "call back", "--today", "2026-11-08"])
        self.assertEqual(len(self.entries()), 2)

    def test_short_text_rejected(self):
        self.assertEqual(self.call(["add", "--person", "rohit", "--text", "ok",
                                    "--today", "2026-11-01"]), 2)
        self.assertEqual(self.entries(), [])

    def test_bad_due_date_rejected(self):
        self.assertEqual(self.call(["add", "--person", "rohit", "--text", "send the draft",
                                    "--due", "12/11", "--today", "2026-11-01"]), 2)
        self.assertEqual(self.entries(), [])

    def test_nonexistent_store_is_created(self):
        self.assertFalse(Path(self.store).exists())
        self.call(["add", "--person", "x", "--text", "the thing", "--today", "2026-11-01"])
        self.assertTrue(Path(self.store).exists())


class ListTest(Store):
    def seed(self):
        self.entries_cache = None
        for person, text, due in [("asha", "send the draft", "2026-10-20"),
                                  ("rohit", "book the call", "2026-12-01"),
                                  ("kavita", "birthday gift", None)]:
            self.call(["add", "--person", person, "--text", text,
                       *(["--due", due] if due else []), "--today", "2026-10-01"])

    def test_list_shows_open_only(self):
        self.seed()
        self.call(["done", self.entries()[0]["id"], "--today", "2026-10-05"])
        self.assertEqual(len([e for e in self.entries() if e["status"] == "open"]), 2)

    def test_list_filters_by_person(self):
        self.seed()
        self.assertEqual(self.call(["list", "--person", "rohit", "--today", "2026-11-01"]), 0)

    def test_store_is_append_only(self):
        self.seed()
        before = len(self.entries())
        self.call(["done", self.entries()[0]["id"], "--today", "2026-10-05"])
        self.assertEqual(len(self.entries()), before)

    def test_overdue_detects_past_due(self):
        self.seed()
        self.assertEqual(self.call(["overdue", "--today", "2026-11-01"]), 0)

    def test_overdue_exits_one_when_clear(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--due", "2026-12-31", "--today", "2026-11-01"])
        self.assertEqual(self.call(["overdue", "--today", "2026-11-02"]), 1)

    def test_no_due_date_is_never_overdue(self):
        self.call(["add", "--person", "asha", "--text", "keep in touch",
                   "--today", "2026-01-01"])
        self.assertEqual(self.call(["overdue", "--today", "2026-11-01"]), 1)


class DoneTest(Store):
    def test_done_sets_closed(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--today", "2026-11-01"])
        eid = self.entries()[0]["id"]
        self.assertEqual(self.call(["done", eid, "--today", "2026-11-05"]), 0)
        entry = self.entries()[0]
        self.assertEqual(entry["status"], "done")
        self.assertEqual(entry["closed"], "2026-11-05")

    def test_done_is_idempotent(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--today", "2026-11-01"])
        eid = self.entries()[0]["id"]
        self.call(["done", eid, "--today", "2026-11-05"])
        self.assertEqual(self.call(["done", eid, "--today", "2026-11-09"]), 0)
        self.assertEqual(self.entries()[0]["closed"], "2026-11-05")

    def test_unknown_id_is_two(self):
        self.assertEqual(self.call(["done", "ffffffff"]), 2)

    def test_prefix_must_be_unique(self):
        Path(self.store).write_text(json.dumps([
            {"id": "aa112233", "person": "aaa", "text": "the first promise",
             "made": "2026-11-01", "due": None, "status": "open", "closed": None},
            {"id": "aa998877", "person": "bbb", "text": "the second promise",
             "made": "2026-11-01", "due": None, "status": "open", "closed": None},
        ]), encoding="utf-8")
        self.assertEqual(self.call(["done", "aa1"]), 0)
        self.assertEqual(self.call(["done", "aa"]), 2)
        self.assertEqual(self.call(["done", "zzzz"]), 2)

    def test_note_is_recorded(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--today", "2026-11-01"])
        eid = self.entries()[0]["id"]
        self.call(["done", eid, "--note", "sent by Lakshya himself", "--today", "2026-11-05"])
        self.assertIn("Lakshya", self.entries()[0]["note"])


class ValidateTest(Store):
    def test_clean_store_passes(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--due", "2026-11-09", "--today", "2026-11-01"])
        self.assertEqual(self.call(["validate"]), 0)

    def test_bad_status_is_caught(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--today", "2026-11-01"])
        entries = self.entries()
        entries[0]["status"] = "cancelled"
        Path(self.store).write_text(json.dumps(entries), encoding="utf-8")
        self.assertEqual(self.call(["validate"]), 1)

    def test_done_without_close_date_is_caught(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--today", "2026-11-01"])
        entries = self.entries()
        entries[0]["status"] = "done"
        entries[0]["closed"] = None
        Path(self.store).write_text(json.dumps(entries), encoding="utf-8")
        self.assertEqual(self.call(["validate"]), 1)

    def test_duplicate_id_is_caught(self):
        self.call(["add", "--person", "asha", "--text", "send the draft",
                   "--today", "2026-11-01"])
        entries = self.entries()
        entries.append(dict(entries[0]))
        Path(self.store).write_text(json.dumps(entries), encoding="utf-8")
        self.assertEqual(self.call(["validate"]), 1)

    def test_corrupt_store_is_two(self):
        Path(self.store).write_text("{not json", encoding="utf-8")
        self.assertEqual(self.call(["validate"]), 2)

    def test_object_store_is_two(self):
        Path(self.store).write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(self.call(["validate"]), 2)


class DateTest(unittest.TestCase):
    def test_today_default_is_a_real_date(self):
        self.assertTrue(pl.DATE_RE.match(pl.today_or(None).isoformat()))

    def test_bad_today_raises(self):
        with self.assertRaises(pl.BadDate):
            pl.today_or("11-2026-01")

    def test_impossible_date_raises(self):
        with self.assertRaises(pl.BadDate):
            pl.parse_date("2026-13-40", "--due")


if __name__ == "__main__":
    unittest.main()
