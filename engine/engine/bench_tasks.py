"""Benchmark tasks for the Engineering engine.

Each task is a small, self-contained programming problem with a real acceptance suite.
The tests are HIDDEN: they live in this module and are copied into the run directory
only after the build finishes, so a lane cannot read them and code to them. What the
lane sees is the problem statement, the required file, and a couple of public examples.

That is what makes the numbers meaningful. A single free model asked once is the
baseline; the engine runs the same problem through its pipeline. Both are scored by the
same hidden tests, so the comparison measures the process, not the prompt.
"""

from __future__ import annotations

TASKS = [
    {
        "id": "interval-merge",
        "title": "Merge overlapping intervals",
        "difficulty": "medium",
        "statement": """Write a Python module `solution.py` exposing:

    merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]

It merges overlapping or touching intervals and returns them sorted by start.
Touching intervals must merge: (1,3) and (3,5) become (1,5).
An empty input returns an empty list. Input must not be mutated.
Intervals may arrive unsorted, and a start may equal its end.

Examples:
    merge_intervals([(1,3),(2,6),(8,10),(15,18)]) == [(1,6),(8,10),(15,18)]
    merge_intervals([(1,4),(4,5)]) == [(1,5)]
""",
        "hidden_tests": '''
import unittest
from solution import merge_intervals

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(merge_intervals([(1,3),(2,6),(8,10),(15,18)]), [(1,6),(8,10),(15,18)])
    def test_touching(self):
        self.assertEqual(merge_intervals([(1,4),(4,5)]), [(1,5)])
    def test_unsorted(self):
        self.assertEqual(merge_intervals([(5,7),(1,2),(2,4)]), [(1,4),(5,7)])
    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])
    def test_single(self):
        self.assertEqual(merge_intervals([(3,3)]), [(3,3)])
    def test_nested(self):
        self.assertEqual(merge_intervals([(1,10),(2,3),(4,5)]), [(1,10)])
    def test_no_mutation(self):
        src = [(5,7),(1,2)]
        merge_intervals(src)
        self.assertEqual(src, [(5,7),(1,2)])
    def test_duplicates(self):
        self.assertEqual(merge_intervals([(1,2),(1,2),(1,2)]), [(1,2)])
    def test_negative(self):
        self.assertEqual(merge_intervals([(-5,-3),(-4,0)]), [(-5,0)])
''',
    },
    {
        "id": "roman-numerals",
        "title": "Roman numeral conversion",
        "difficulty": "medium",
        "statement": """Write a Python module `solution.py` exposing:

    to_roman(n: int) -> str
    from_roman(s: str) -> int

`to_roman` converts 1..3999 using standard subtractive notation (4 is IV, 9 is IX,
40 is XL, 900 is CM). Values outside 1..3999 raise ValueError.
`from_roman` parses a canonical uppercase numeral back to an int, and raises
ValueError on an empty string or any character outside IVXLCDM.

Examples:
    to_roman(1994) == "MCMXCIV"
    from_roman("MCMXCIV") == 1994
""",
        "hidden_tests": '''
import unittest
from solution import to_roman, from_roman

class T(unittest.TestCase):
    def test_units(self):
        for n, s in [(1,"I"),(2,"II"),(3,"III"),(5,"V"),(6,"VI"),(7,"VII"),(8,"VIII")]:
            self.assertEqual(to_roman(n), s, n)
    def test_subtractive(self):
        for n, s in [(4,"IV"),(9,"IX"),(40,"XL"),(90,"XC"),(400,"CD"),(900,"CM")]:
            self.assertEqual(to_roman(n), s, n)
    def test_compound(self):
        for n, s in [(1994,"MCMXCIV"),(2026,"MMXXVI"),(3999,"MMMCMXCIX"),
                     (444,"CDXLIV"),(1987,"MCMLXXXVII"),(3549,"MMMDXLIX")]:
            self.assertEqual(to_roman(n), s, n)
    def test_roundtrip_all(self):
        for n in range(1, 4000):
            self.assertEqual(from_roman(to_roman(n)), n, n)
    def test_parse_known(self):
        for s, n in [("MCMXCIV",1994),("MMMCMXCIX",3999),("IX",9),("XL",40)]:
            self.assertEqual(from_roman(s), n, s)
    def test_too_small(self):
        for bad in (0, -1, -100):
            with self.assertRaises(ValueError):
                to_roman(bad)
    def test_too_large(self):
        for bad in (4000, 5000, 10000):
            with self.assertRaises(ValueError):
                to_roman(bad)
    def test_empty_string(self):
        with self.assertRaises(ValueError):
            from_roman("")
    def test_invalid_chars(self):
        for bad in ("ABC", "IIIIIXYZ", "hello", "MCMX2"):
            with self.assertRaises(ValueError):
                from_roman(bad)
''',
    },
    {
        "id": "lru-cache",
        "title": "LRU cache with capacity",
        "difficulty": "high",
        "statement": """Write a Python module `solution.py` exposing a class:

    LRUCache(capacity: int)
        .get(key) -> value or None if absent
        .put(key, value) -> None
        .__len__() -> number of stored entries

`get` and `put` both count as a use, so they refresh recency. When a put would exceed
capacity, evict the least recently used entry. A capacity of 0 stores nothing.
A capacity below 0 raises ValueError. Updating an existing key must not evict anything.
Do not use functools.lru_cache or OrderedDict; implement the ordering yourself.

Examples:
    c = LRUCache(2); c.put("a",1); c.put("b",2)
    c.get("a") == 1; c.put("c",3)   # evicts "b"
    c.get("b") is None
""",
        "hidden_tests": '''
import unittest
from solution import LRUCache

class T(unittest.TestCase):
    def test_eviction_order(self):
        c = LRUCache(2); c.put("a",1); c.put("b",2)
        self.assertEqual(c.get("a"), 1)
        c.put("c",3)
        self.assertIsNone(c.get("b"))
        self.assertEqual(c.get("c"), 3)
    def test_get_refreshes(self):
        c = LRUCache(2); c.put(1,1); c.put(2,2); c.get(1); c.put(3,3)
        self.assertEqual(c.get(1), 1)
        self.assertIsNone(c.get(2))
    def test_update_no_evict(self):
        c = LRUCache(2); c.put("a",1); c.put("b",2); c.put("a",9)
        self.assertEqual(len(c), 2)
        self.assertEqual(c.get("a"), 9)
        self.assertEqual(c.get("b"), 2)
    def test_len(self):
        c = LRUCache(3)
        for i in range(5):
            c.put(i, i)
            self.assertLessEqual(len(c), 3)
        self.assertEqual(len(c), 3)
    def test_zero_capacity(self):
        c = LRUCache(0); c.put("a",1)
        self.assertIsNone(c.get("a")); self.assertEqual(len(c), 0)
    def test_negative_capacity(self):
        with self.assertRaises(ValueError):
            LRUCache(-1)
    def test_missing_key(self):
        self.assertIsNone(LRUCache(2).get("nope"))
    def test_no_stdlib_shortcut(self):
        src = open("solution.py").read()
        self.assertNotIn("OrderedDict", src)
        self.assertNotIn("lru_cache", src)
''',
    },
    {
        "id": "csv-group",
        "title": "CSV grouping with numeric aggregation",
        "difficulty": "medium",
        "statement": """Write a Python module `solution.py` exposing:

    group_sum(csv_text: str, key_col: str, value_col: str) -> dict[str, float]

Parses CSV text (with a header row), groups rows by `key_col`, and sums `value_col`
per group as floats. Quoted fields containing commas must parse correctly. Rows whose
value is empty or not a number are skipped, not crashed on. A missing column raises
KeyError. An empty input (no header) returns {}. Keys keep their first-seen order.

Examples:
    group_sum("k,v\\na,1\\nb,2\\na,3\\n", "k", "v") == {"a": 4.0, "b": 2.0}
""",
        "hidden_tests": '''
import unittest
from solution import group_sum

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(group_sum("k,v\\na,1\\nb,2\\na,3\\n","k","v"), {"a":4.0,"b":2.0})
    def test_quoted_comma(self):
        txt = 'k,v\\n"a,b",1\\n"a,b",2\\n'
        self.assertEqual(group_sum(txt,"k","v"), {"a,b":3.0})
    def test_bad_values_skipped(self):
        txt = "k,v\\na,1\\na,\\na,x\\na,2\\n"
        self.assertEqual(group_sum(txt,"k","v"), {"a":3.0})
    def test_floats(self):
        self.assertAlmostEqual(group_sum("k,v\\na,1.5\\na,2.25\\n","k","v")["a"], 3.75)
    def test_missing_column(self):
        with self.assertRaises(KeyError):
            group_sum("k,v\\na,1\\n","k","nope")
    def test_empty(self):
        self.assertEqual(group_sum("","k","v"), {})
    def test_header_only(self):
        self.assertEqual(group_sum("k,v\\n","k","v"), {})
    def test_order(self):
        out = group_sum("k,v\\nz,1\\na,1\\nm,1\\n","k","v")
        self.assertEqual(list(out), ["z","a","m"])
    def test_negative(self):
        self.assertEqual(group_sum("k,v\\na,5\\na,-2\\n","k","v"), {"a":3.0})
''',
    },
    {
        "id": "topo-sort",
        "title": "Topological sort with cycle detection",
        "difficulty": "high",
        "statement": """Write a Python module `solution.py` exposing:

    topo_sort(graph: dict[str, list[str]]) -> list[str]

`graph` maps a node to the nodes it depends on. Return an order where every node comes
after all of its dependencies. Nodes that appear only as dependencies must be included.
Among nodes that are ready at the same time, choose the alphabetically smallest first,
so the result is deterministic. If there is a cycle, raise ValueError. An empty graph
returns []. The input must not be mutated.

Examples:
    topo_sort({"a": ["b"], "b": []}) == ["b", "a"]
    topo_sort({"a": ["b"], "b": ["a"]}) raises ValueError
""",
        "hidden_tests": '''
import unittest
from solution import topo_sort

class T(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(topo_sort({"a":["b"],"b":[]}), ["b","a"])
    def test_implicit_nodes(self):
        self.assertEqual(topo_sort({"a":["z"]}), ["z","a"])
    def test_deterministic(self):
        g = {"d":["b","c"], "b":[], "c":[]}
        self.assertEqual(topo_sort(g), ["b","c","d"])
    def test_cycle(self):
        with self.assertRaises(ValueError):
            topo_sort({"a":["b"],"b":["a"]})
    def test_self_cycle(self):
        with self.assertRaises(ValueError):
            topo_sort({"a":["a"]})
    def test_empty(self):
        self.assertEqual(topo_sort({}), [])
    def test_diamond(self):
        g = {"a":["b","c"], "b":["d"], "c":["d"], "d":[]}
        order = topo_sort(g)
        for node, deps in g.items():
            for dep in deps:
                self.assertLess(order.index(dep), order.index(node))
    def test_no_mutation(self):
        g = {"a":["b"],"b":[]}
        import copy
        before = copy.deepcopy(g)
        topo_sort(g)
        self.assertEqual(g, before)
    def test_long_chain(self):
        g = {f"n{i}": [f"n{i+1}"] for i in range(200)}
        g["n200"] = []
        self.assertEqual(len(topo_sort(g)), 201)
''',
    },
]


def by_id(task_id: str) -> dict:
    for task in TASKS:
        if task["id"] == task_id:
            return task
    raise KeyError(task_id)


HARD_TASKS = [
    {
        "id": "expr-eval",
        "title": "Arithmetic expression evaluator",
        "difficulty": "high",
        "statement": """Write a Python module `solution.py` exposing:

    evaluate(expr: str) -> float

Evaluates an arithmetic expression given as a string. Rules, all of which are tested:
- Operators: + - * / and ** (power). Also parentheses.
- Precedence, low to high: + and -, then * and /, then unary minus, then **.
- ** is RIGHT associative: 2**3**2 == 512.
- Unary minus binds looser than **: -2**2 == -4, and 2**-2 == 0.25.
- / is true division. Division by zero raises ZeroDivisionError.
- Whitespace anywhere is ignored. Numbers may be integers or decimals like 3.5 or .5.
- Malformed input (empty string, unbalanced parentheses, a stray letter, a trailing
  operator, two binary operators in a row, two adjacent numbers) raises ValueError.
  A unary sign after a binary operator is valid: 2*-3 and 2--3 are fine.
- Do NOT use eval, exec, compile or ast.literal_eval. Parse it yourself.

Examples:
    evaluate("2+3*4") == 14.0
    evaluate("2**3**2") == 512.0
    evaluate("-2**2") == -4.0
""",
        "hidden_tests": '''
import unittest
from solution import evaluate

class T(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(evaluate("2+3*4"), 14.0)
        self.assertEqual(evaluate("2*3+4"), 10.0)
        self.assertEqual(evaluate("10-2-3"), 5.0)
    def test_parens(self):
        self.assertEqual(evaluate("(2+3)*4"), 20.0)
        self.assertEqual(evaluate("((2))"), 2.0)
    def test_power_right_assoc(self):
        self.assertEqual(evaluate("2**3**2"), 512.0)
    def test_unary_and_power(self):
        self.assertEqual(evaluate("-2**2"), -4.0)
        self.assertEqual(evaluate("2**-2"), 0.25)
        self.assertEqual(evaluate("(-2)**2"), 4.0)
    def test_unary_chains(self):
        self.assertEqual(evaluate("--3"), 3.0)
        self.assertEqual(evaluate("2*-3"), -6.0)
        self.assertEqual(evaluate("2--3"), 5.0)
    def test_decimals_and_space(self):
        self.assertAlmostEqual(evaluate(" .5 + 1.25 "), 1.75)
        self.assertEqual(evaluate("3.5*2"), 7.0)
    def test_true_division(self):
        self.assertEqual(evaluate("7/2"), 3.5)
    def test_div_zero(self):
        with self.assertRaises(ZeroDivisionError):
            evaluate("1/0")
    def test_malformed(self):
        for bad in ("", "  ", "2+", "(2+3", "2+3)", "abc", "2 3", "2**", "*3"):
            with self.assertRaises(ValueError, msg=bad):
                evaluate(bad)
    def test_no_eval_shortcut(self):
        import re as _re
        src = open("solution.py").read()
        # re.compile is legitimate tokenising; only evaluating code is banned.
        for pattern in (r"(?<![\\w.])eval\\s*\\(", r"(?<![\\w.])exec\\s*\\(",
                        r"literal_eval", r"(?<!re\\.)compile\\s*\\("):
            self.assertIsNone(_re.search(pattern, src), pattern)
''',
    },
    {
        "id": "semver-range",
        "title": "Semantic version comparison and range matching",
        "difficulty": "high",
        "statement": """Write a Python module `solution.py` exposing:

    compare(a: str, b: str) -> int      # -1 if a<b, 0 if equal, 1 if a>b
    satisfies(version: str, range_spec: str) -> bool

Versions are MAJOR.MINOR.PATCH, optionally with a prerelease suffix after '-'
(for example 1.2.3-alpha.1). Build metadata after '+' is ignored entirely.

Comparison rules:
- Compare major, then minor, then patch numerically.
- A version WITH a prerelease is LOWER than the same version without one:
  1.0.0-alpha < 1.0.0.
- Prerelease identifiers compare left to right. Numeric identifiers compare numerically
  and rank BELOW alphanumeric ones. If all shared identifiers are equal, the shorter
  prerelease list is lower: alpha < alpha.1.

Range specs, each a single clause:
- exact "1.2.3"; comparison ">1.2.3", ">=1.2.3", "<1.2.3", "<=1.2.3"
- caret "^1.2.3" means >=1.2.3 and <2.0.0. For ^0.2.3 it means >=0.2.3 and <0.3.0.
  For ^0.0.3 it means >=0.0.3 and <0.0.4.
- tilde "~1.2.3" means >=1.2.3 and <1.3.0. "~1.2" means >=1.2.0 and <1.3.0.
- A prerelease version only satisfies a range if the range's own base version has a
  prerelease with the same major.minor.patch. So 1.2.3-alpha does NOT satisfy ^1.2.0,
  but DOES satisfy ^1.2.3-alpha.
Malformed versions raise ValueError. A missing minor or patch defaults to 0 in a range
base, but a version argument must have all three parts.

Examples:
    compare("1.0.0-alpha", "1.0.0") == -1
    satisfies("1.5.0", "^1.2.3") is True
    satisfies("2.0.0", "^1.2.3") is False
""",
        "hidden_tests": '''
import unittest
from solution import compare, satisfies

class T(unittest.TestCase):
    def test_numeric_order(self):
        self.assertEqual(compare("1.2.3","1.2.4"), -1)
        self.assertEqual(compare("2.0.0","1.9.9"), 1)
        self.assertEqual(compare("1.2.3","1.2.3"), 0)
        self.assertEqual(compare("1.10.0","1.9.0"), 1)
    def test_prerelease_lower(self):
        self.assertEqual(compare("1.0.0-alpha","1.0.0"), -1)
        self.assertEqual(compare("1.0.0","1.0.0-alpha"), 1)
    def test_prerelease_ordering(self):
        self.assertEqual(compare("1.0.0-alpha","1.0.0-beta"), -1)
        self.assertEqual(compare("1.0.0-alpha","1.0.0-alpha.1"), -1)
        self.assertEqual(compare("1.0.0-alpha.2","1.0.0-alpha.10"), -1)
        self.assertEqual(compare("1.0.0-1","1.0.0-alpha"), -1)
    def test_build_metadata_ignored(self):
        self.assertEqual(compare("1.2.3+build5","1.2.3+build9"), 0)
        self.assertEqual(compare("1.2.3-a+1","1.2.3-a+2"), 0)
    def test_exact_and_comparators(self):
        self.assertTrue(satisfies("1.2.3","1.2.3"))
        self.assertFalse(satisfies("1.2.4","1.2.3"))
        self.assertTrue(satisfies("1.2.4",">1.2.3"))
        self.assertFalse(satisfies("1.2.3",">1.2.3"))
        self.assertTrue(satisfies("1.2.3",">=1.2.3"))
        self.assertTrue(satisfies("1.2.3","<=1.2.3"))
        self.assertTrue(satisfies("1.2.2","<1.2.3"))
    def test_caret(self):
        self.assertTrue(satisfies("1.5.0","^1.2.3"))
        self.assertFalse(satisfies("2.0.0","^1.2.3"))
        self.assertFalse(satisfies("1.2.2","^1.2.3"))
        self.assertTrue(satisfies("0.2.9","^0.2.3"))
        self.assertFalse(satisfies("0.3.0","^0.2.3"))
        self.assertTrue(satisfies("0.0.3","^0.0.3"))
        self.assertFalse(satisfies("0.0.4","^0.0.3"))
    def test_tilde(self):
        self.assertTrue(satisfies("1.2.9","~1.2.3"))
        self.assertFalse(satisfies("1.3.0","~1.2.3"))
        self.assertTrue(satisfies("1.2.0","~1.2"))
        self.assertFalse(satisfies("1.3.0","~1.2"))
    def test_prerelease_range_gate(self):
        self.assertFalse(satisfies("1.2.3-alpha","^1.2.0"))
        self.assertTrue(satisfies("1.2.3-alpha","^1.2.3-alpha"))
        self.assertTrue(satisfies("1.2.3-beta","^1.2.3-alpha"))
        self.assertFalse(satisfies("1.3.0-alpha","^1.2.3-alpha"))
    def test_malformed(self):
        for bad in ("1.2", "1", "a.b.c", "", "1.2.3.4"):
            with self.assertRaises(ValueError, msg=bad):
                compare(bad, "1.0.0")
''',
    },
    {
        "id": "justify-text",
        "title": "Full text justification",
        "difficulty": "high",
        "statement": """Write a Python module `solution.py` exposing:

    justify(words: list[str], width: int) -> list[str]

Greedy line wrapping then full justification, like the classic typesetting problem.
- Pack as many words as fit on a line, separated by at least one space.
- Pad each line to exactly `width` characters by distributing extra spaces between
  words. When the spaces do not divide evenly, the LEFTMOST gaps get the extra spaces.
- A line with a single word is left-aligned and padded on the right.
- The LAST line is always left-aligned with single spaces between words, then padded
  on the right.
- A word longer than `width` occupies its own line and is NOT truncated; that line is
  allowed to exceed width.
- Empty input returns []. A width below 1 raises ValueError.
- No line other than an over-long single word may exceed width.

Examples:
    justify(["a","b","c"], 5) == ["a b c"]
    justify(["this","is","an","example"], 11) == ["this  is an", "example    "]
""",
        "hidden_tests": '''
import unittest
from solution import justify

class T(unittest.TestCase):
    def test_exact_fit(self):
        self.assertEqual(justify(["a","b","c"], 5), ["a b c"])
    def test_leftmost_extra_spaces(self):
        self.assertEqual(justify(["this","is","an","example"], 11),
                         ["this  is an", "example    "])
    def test_single_word_lines(self):
        self.assertEqual(justify(["hello","world"], 5), ["hello", "world"])
    def test_overlong_word_not_truncated(self):
        out = justify(["abcdefghij","x"], 5)
        self.assertEqual(out[0], "abcdefghij")
        self.assertEqual(out[-1].strip(), "x")
    def test_empty(self):
        self.assertEqual(justify([], 10), [])
    def test_bad_width(self):
        for w in (0, -1):
            with self.assertRaises(ValueError):
                justify(["a"], w)
    def test_all_lines_exact_width(self):
        words = "the quick brown fox jumps over the lazy dog again".split()
        out = justify(words, 16)
        for line in out[:-1]:
            self.assertEqual(len(line), 16, repr(line))
        self.assertEqual(len(out[-1]), 16, repr(out[-1]))
    def test_distribution_order(self):
        # A following line is needed, otherwise this is the last line and is left-aligned.
        out = justify(["a","b","c","d","eeeeeeee"], 10)
        self.assertEqual(out[0], "a  b  c  d")
        self.assertEqual(out[1].strip(), "eeeeeeee")
    def test_last_line_left_aligned(self):
        self.assertEqual(justify(["one","two","three"], 20)[-1],
                         "one two three".ljust(20))
    def test_words_all_preserved(self):
        words = "alpha beta gamma delta epsilon zeta".split()
        self.assertEqual(" ".join(justify(words, 12)).split(), words)
''',
    },
]

TASKS.extend(HARD_TASKS)


# ------------------------------------------------------------------
# Research department tasks: see the module docstring above. The
# thresholds under "hidden" keys are never written into a lane prompt;
# the grader is generated into the workdir only after the memo is done.
RESEARCH_TASKS = [
    {
        "id": "decision-archive-host",
        "title": "Decision memo: where the club's event photos live",
        "kind": "decision",
        "agent": "research-2",
        "difficulty": "high",
        "statement": """## Question
For Code.SCRIET's event-photo archive -- roughly 40 GB of originals today, growing
about 2 GB a year, containing members' faces -- is (A) a private GitHub repository with
the images committed, or (B) Cloudflare R2 fronted by Cloudflare Pages, the better home
for a gallery the club can actually serve, given that no account may carry a card and
the images must not sit in a public repository?

## Why it matters / the decision this feeds
The CEO decides this month which archive layout Engineering implements. The wrong answer
either exposes members' photos to the internet or leaves the club with an archive it
cannot serve to visitors at all.

## What the memo has to do
- Compare exactly these two options, in a trade-off table, on: the exact free-tier
  limit and its unit, what happens when that limit is reached (429, a pause, a hang, a
  silent fallback to a paid plan), whether a card or the Owner's sign-in is needed to
  open the account, and what each option does to the privacy of the images.
- State the hard constraints before the options, and test each option against them.
- Name one recommendation, with the strongest reason for it and what would change it.
- Report the setup steps the executing department would have to take. Research does not
  take them; recommending is the whole job here.
- Cite only pages you opened yourself during this run, with the web fetch tool or curl,
  and give the date you checked each one. Every factual claim carries its citation;
  anything you concluded rather than read is marked as an inference.
- Do not recommend a paid plan, a paid tier or a trial that needs a card as an answer.

Deliverable: ONE decision memo in markdown at the path given in the task brief, at the
department's memo format, passing this department's gates.""",
        # ---- hidden thresholds: never shown to a lane -------------------------
        "min_sources": 5,
        "min_domains": 2,
        "required_hosts": ["github.com", "cloudflare.com"],
        "min_words": 600,
        "max_words": 2600,
        "min_blocks": 3,
        "min_cited_share": 0.5,
        "min_fact_bullets": 6,
        "option_terms": ["github", "cloudflare", "r2", "pages"],
        "min_option_terms": 2,
        "min_table_rows": 4,
        "needs_constraints_block": True,
        "needs_limit_behaviour": True,
        "min_premortem_causes": 3,
        "min_memo_bytes": 1500,
        "headings": ["question", "why", "findings", "options", "recommendation",
                     "pre-mortem", "open questions", "sources"],
    },
    {
        "id": "scan-free-alerting",
        "title": "Landscape scan: free tiers that can carry an engine alarm",
        "kind": "quick",
        "agent": "research-1",
        "difficulty": "medium",
        "statement": """## Question
Which free tiers among GlitchTip, Sentry's free developer tier, UptimeRobot, Better
Stack, Grafana Cloud free and healthchecks.io can carry an alarm when an engctl run
fails -- with no card on any account and no paid tier underneath -- and what exactly
happens at each one's free limit?

## Why it matters / the decision this feeds
Engine runs finish at night and nobody watches RUN_REPORT.md. Platform needs one named
target for a run-failure alarm this month, chosen from free tiers only, and needs to
know how that target fails when its quota is gone.

## What the memo has to do
- One Findings block per candidate you keep, each reporting: the exact free limit and
  its unit, whether the tier is standing or a one-time signup grant, what happens when
  it is reached, and whether opening it needs a card, a phone number or the Owner's
  sign-in.
- Say plainly which candidates you dropped and what made them drop out.
- Cover at least three of the named candidates in the comparison table.
- Compare the survivors in a trade-off table, name one recommendation with the reason
  and what would change it.
- Cite only pages you opened yourself during this run, with the web fetch tool or curl,
  and give the date you checked each one. Every factual claim carries its citation;
  anything concluded rather than read is marked as an inference.
- A tier that needs a card, or that is only a trial, is reported as such and not
  recommended.

Deliverable: ONE quick memo in markdown at the path given in the task brief, at the
department's memo format, passing this department's gates.""",
        "min_sources": 6,
        "min_domains": 4,
        "required_hosts": [],
        "min_words": 550,
        "max_words": 2600,
        "min_blocks": 3,
        "min_cited_share": 0.5,
        "min_fact_bullets": 6,
        "option_terms": ["glitchtip", "sentry", "uptimerobot", "better stack",
                         "grafana", "healthchecks"],
        "min_option_terms": 3,
        "min_table_rows": 4,
        "needs_constraints_block": False,
        "needs_limit_behaviour": True,
        "min_premortem_causes": 0,
        "min_memo_bytes": 1500,
        "headings": ["question", "why", "findings", "options", "recommendation",
                     "open questions", "sources"],
    },
]


# ---------------------------------------------------------------- negative probes

def research_task(task_id: str) -> dict:
    for task in RESEARCH_TASKS:
        if task["id"] == task_id:
            return task
    raise KeyError(task_id)


# A memo that is deliberately correct, used as the base every defect is injected into.
# Its sources are live pages whose text was read on 2026-10-31, and the figures below
# come from them.
GOOD_DECISION_MEMO = """# Research Memo: the event-photo archive on free tiers only

**Agent:** research-2
**Date:** 2026-10-31
**Issue:** R07 research benchmark, decision memo

## Question
For Code.SCRIET's event-photo archive, roughly 40 GB of originals growing about 2 GB a
year and containing members' faces, is a private GitHub repository with the images
committed, or Cloudflare R2 fronted by Cloudflare Pages, the better home for a gallery
the club can serve, given that no account may carry a card and the images must not sit
in a public repository?
Requested by: CEO.

## Why it matters / decision this feeds
The CEO picks the archive layout this month and Engineering implements it. The wrong
answer either publishes members' faces to the internet or leaves the club holding an
archive it cannot serve.

## Findings

### Constraints from first principles
**Facts:**
- The company runs only on free models and free tiers, and no option may need a card
  (departments/research/CHARTER.md:9).
- Research recommends and never executes, so the setup steps below belong to
  Engineering (departments/research/CHARTER.md:31).
- A GitHub repository should stay within 10 GB of on-disk size, and GitHub states that
  exceeding the recommended maximum risks degraded repository health
  (https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits).

**Inferences:**
- 40 GB of originals is four times that recommended repository size, so option A is
  outside the guidance before privacy is even considered.

### A: private GitHub repository with images committed
**Facts:**
- Private repositories are supported on every plan for code, but GitHub Pages for a
  private repository is a paid-plan feature, so the images could be stored without a
  card yet not served from Pages (https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
- A published Pages site may be no larger than 1 GB, and Pages source repositories have
  a recommended limit of 1 GB (https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
- Pages sites have a soft bandwidth limit of 100 GB per month and a soft limit of 10
  builds per hour, which does not apply to a custom GitHub Actions workflow
  (https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
- When a Pages request trips a rate limit GitHub returns HTTP status 429 with an HTML
  body, and says it may stop serving a site that exceeds the quotas
  (https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).

**Inferences:**
- Keeping the archive private means the gallery needs a separate delivery path, because
  the storage that is free and the serving that is free are not the same repository.

### B: Cloudflare R2 fronted by Cloudflare Pages
**Facts:**
- Cloudflare Pages on the Free plan gets 500 builds per month and 1 build at a time,
  with a 20-minute build timeout
  (https://developers.cloudflare.com/pages/platform/limits/).
- The Free plan allows 100 custom domains per Pages project
  (https://developers.cloudflare.com/pages/platform/limits/).
- R2 reports unlimited data storage per bucket and unlimited objects per bucket in its
  published limits table (https://developers.cloudflare.com/r2/reference/limits/).
- R2 buckets are reachable through an S3-compatible API and a Workers API, and a managed
  public bucket served through an r2.dev subdomain is explicitly not intended for
  production use (https://developers.cloudflare.com/r2/reference/limits/).
- Exceeding the r2.dev rate limit throttles requests with a 429 Too Many Requests
  response, and throughput may also be throttled there
  (https://developers.cloudflare.com/r2/reference/limits/).
- The Cloudflare REST API for R2 is limited to 1,200 requests per five minutes per
  account (https://developers.cloudflare.com/r2/reference/limits/).
- R2 is sold as object storage without the egress bandwidth fees typical of cloud
  storage (https://developers.cloudflare.com/r2/).

**Inferences:**
- Serving the gallery needs a custom domain on the bucket or Pages functions in front of
  it, because the free r2.dev test endpoint throttles exactly the traffic a gallery
  generates.
- Neither Cloudflare limit quoted above is a card gate: the Pages Free plan and the R2
  limits page both describe the free tier itself
  (https://developers.cloudflare.com/pages/platform/limits/).

### Where the sources disagree
**Facts:**
- GitHub describes 100 GB per month as a soft limit that may simply stop being served,
  while Cloudflare's Pages table lists counts per month with a limit-increase request
  form (https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
- Neither vendor states a hard stop in advance, so the failure mode has to be read from
  the 429 behaviour both documents, not from a published cap
  (https://developers.cloudflare.com/r2/reference/limits/).

## Options & trade-offs

| Criterion | A: private GitHub repo | B: R2 plus Cloudflare Pages | Do nothing |
|---|---|---|---|
| Free-tier limit that binds first | 10 GB recommended on-disk size per repository [1] | 500 builds per month, 1 concurrent [2] | none |
| What happens at the limit | HTTP 429, or the site may stop being served [1] | 429 throttling on the r2.dev test endpoint [3] | archive stays unsearchable |
| Card or Owner sign-in needed | no, storage is free on private repos [1] | no for Pages Free and R2 limits [2] | no |
| Privacy of members' faces | private by default, must never be public [1] | private bucket, public only through a domain you attach [3] | photos stay on laptops |
| Setup Engineering must do | none for storage; a separate server for a gallery | bucket plus custom domain plus a Pages project [3] | none |
| Reversibility | high: git history holds every face forever | medium: objects can be deleted, git history untouched | n/a |

## Recommendation
Take option B: Cloudflare R2 for the originals behind a private bucket, fronted by
Cloudflare Pages for the gallery, with a custom domain attached so the free r2.dev test
endpoint is never the thing serving visitors. Option A fails the first constraint it
meets: 40 GB is four times the 10 GB on-disk size GitHub recommends for a repository
[1], and committing images means every future member can check out every face the club
ever photographed. B keeps the originals out of git, states its free limits as counts
rather than as a paid upgrade path [2], and throttles rather than bills when it runs
over [3].

What would change it: if Cloudflare requires a card to open an R2 bucket even at zero
usage, or if the club agrees to keep only web-sized derivatives and deletes the
originals, then a public repository of resized photos becomes the cheaper answer.

## Pre-mortem
Assume it is 2027-01-31 and this recommendation failed.
1. The gallery was served through the r2.dev test endpoint and throttled with 429 during
   the freshest event's traffic, because nobody attached a custom domain. Early signal:
   429s in the Pages analytics for that bucket [3]. Guard: Engineering adds a pre-deploy
   check that the gallery's origin is a custom domain, not r2.dev.
2. The private bucket was switched to a managed public bucket to make the gallery easier
   to link, publishing every original. Early signal: a bucket whose storage type reads
   as public. Guard: the bucket-lock or account-level setting that forbids public
   buckets is set the day the bucket is created [3].
3. The free build count ran out mid-semester, so new events never appeared. Early
   signal: build count per month approaching 500 [2]. Guard: build the gallery list at
   request time rather than rebuilding the site per photo.

## Open questions
- Does opening a Cloudflare account with R2 require a card at signup? The limits and
  pricing pages do not say, and only the Owner can settle it by reaching the signup form.
- Are the 1,200 REST API requests per five minutes per account or per bucket for R2
  [3]? The page does not say, and it matters if the gallery lists objects per request.
- How many originals is 40 GB actually, and how many does the club intend to publish
  at full size? The club holds the answer.

## Sources
[1] GitHub, Repository limits - https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits (checked 2026-10-31)
[2] Cloudflare Pages, Limits - https://developers.cloudflare.com/pages/platform/limits/ (checked 2026-10-31)
[3] Cloudflare R2, Limits - https://developers.cloudflare.com/r2/reference/limits/ (checked 2026-10-31)
[4] GitHub Pages, GitHub Pages limits - https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits (checked 2026-10-31)
[5] Cloudflare R2, Overview - https://developers.cloudflare.com/r2/ (checked 2026-10-31)
[6] Research department charter - departments/research/CHARTER.md:9 (checked 2026-10-31)

RESULT: DONE
"""


# One defect injected into GOOD_DECISION_MEMO at a time. Every row says which check is
# supposed to catch it. If a row is not caught, that check is decorative.
#
# Ops: sub [pattern, repl, count] / delete_section <title> / cut_from <heading line>
#      move_section_before [moved, target] / replace_section_body [title, text]
#      delete_lines_matching <pattern>
RESEARCH_GATE_PROBES = [
    {"name": "good-memo", "expect": "passes-everything", "edits": []},
    {"name": "uncited-fact-bullet", "expect": "gate:dept:cited:memo.md",
     "needle": "claim has no citation",
     "edits": [{"sub": [r"storage \(https://developers\.cloudflare\.com/r2/\)\.",
                        "storage.", 1]}]},
    {"name": "dangling-reference", "expect": "gate:dept:cited:memo.md",
     "needle": "not listed in Sources",
     "edits": [{"sub": [r"per repository \[1\]", "per repository [9]", 1]}]},
    {"name": "malformed-url", "expect": "gate:dept:cited:memo.md",
     "needle": "no dot",
     "edits": [{"sub": [r"https://developers\.cloudflare\.com/r2/reference/limits/",
                        "https://cloudflaredocs/r2-limits", 1]}]},
    {"name": "sources-section-deleted", "expect": "gate:dept:cited:memo.md",
     "needle": "no Sources section",
     "edits": [{"cut_from": "## Sources"}]},
    {"name": "placeholder-left-in", "expect": "gate:dept:memo-format:memo.md",
     "needle": "[insert",
     "edits": [{"sub": [r"## Recommendation\nTake option B",
                        "## Recommendation\n[insert the pick here]\nTake option B", 1]}]},
    {"name": "recommendation-deleted", "expect": "gate:dept:memo-format:memo.md",
     "needle": "missing section",
     "edits": [{"delete_section": "Recommendation"}]},
    {"name": "sections-out-of-order", "expect": "gate:dept:memo-format:memo.md",
     "needle": "out of order",
     "edits": [{"move_section_before": ["Sources", "Open questions"]}]},
    {"name": "thin-recommendation", "expect": "gate:dept:memo-format:memo.md",
     "needle": "too thin",
     "edits": [{"replace_section_body": ["Recommendation", "Use B."]}]},
    {"name": "premortem-deleted", "expect": "gate:memo-format-decision",
     "needle": "pre-mortem",
     "edits": [{"delete_section": "Pre-mortem"}],
     "note": ("the kit's memo-format gate runs memo_lint with no --kind, so with the "
              "Pre-mortem gone auto falls back to the quick order and passes: only a "
              "kind-aware gate catches this")},
    {"name": "number-invented-outside-findings",
     "expect": "hidden:test_numbers_outside_findings_trace_to_a_cited_claim",
     "edits": [{"sub": [r"10 GB recommended on-disk size per repository \[1\]",
                        "250 GB recommended on-disk size per repository", 1]}]},
    {"name": "invented-url", "expect": "hidden:test_source_urls_are_reachable",
     "edits": [{"sub": [r"\[5\] Cloudflare R2, Overview - https://developers\.cloudflare"
                        r"\.com/r2/ \(checked 2026-10-31\)",
                        "[5] Cloudflare R2, Storage and bandwidth limits - https://developers"
                        ".cloudflare.com/r2/basics/storage-and-bandwidth-limits/ "
                        "(checked 2026-10-31)", 1]}]},
    {"name": "too-few-sources", "expect": "hidden:test_sources_lists_enough_distinct_urls",
     "edits": [{"delete_lines_matching": r"^\[[4-6]\].*$"}]},
    {"name": "undated-sources", "expect": "hidden:test_every_source_is_dated",
     "edits": [{"sub": [r"\(checked 2026-10-31\)", "(undated)", 0]}]},
]
