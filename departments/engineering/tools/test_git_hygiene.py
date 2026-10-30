"""Tests for git_hygiene.py. Builds throwaway repositories in temp dirs; never touches a real repo."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import git_hygiene as gh  # noqa: E402


class GitHygieneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        cfg = self.base / "gitconfig"
        cfg.write_text("[user]\n\tname = Test\n\temail = test@example.invalid\n"
                       "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n")
        self.env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(cfg),
                                                "GIT_CONFIG_NOSYSTEM": "1"})
        self.env.start()
        self.remote = self.base / "remote.git"
        self.sh("git", "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.repo = self.base / "work"
        self.sh("git", "clone", "-q", str(self.remote), str(self.repo))
        self.commit("README.md", "hello\n", "first")
        self.sh("git", "-C", str(self.repo), "push", "-q", "-u", "origin", "main")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def sh(self, *args):
        subprocess.run(args, check=True, capture_output=True, text=True)

    def g(self, *args):
        self.sh("git", "-C", str(self.repo), *args)

    def commit(self, name, text, msg):
        (self.repo / name).write_text(text)
        self.g("add", name)
        self.g("commit", "-q", "-m", msg)

    def run_tool(self, path=None, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = gh.main([str(path or self.repo), "--json", *extra])
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip().startswith("{") else None), err.getvalue()

    def test_clean_pushed_repo_passes(self):
        rc, rep, err = self.run_tool()
        self.assertEqual(rc, 0, rep)
        self.assertEqual(rep["branch"], "main")
        self.assertEqual(rep["at_risk"], [])
        self.assertEqual(rep["branches"][0]["state"], "pushed")
        self.assertEqual(err, "")

    def test_local_branch_with_no_upstream_fails(self):
        self.g("checkout", "-q", "-b", "feat/cert-templates-api")
        self.commit("cert.py", "x = 1\n", "phase 1")
        rc, rep, err = self.run_tool()
        self.assertEqual(rc, 1)
        self.assertIn("feat/cert-templates-api", rep["at_risk"])
        self.assertIn("has no upstream", " ".join(rep["problems"]))
        self.assertIn("git_hygiene:", err)

    def test_branch_ahead_of_upstream_fails(self):
        self.commit("b.txt", "b\n", "second")
        rc, rep, _ = self.run_tool()
        self.assertEqual(rc, 1)
        main = rep["branches"][0]
        self.assertEqual(main["state"], "ahead 1")
        self.assertEqual(main["unique_commits"], 1)

    def test_branch_without_upstream_but_no_new_commits_is_safe(self):
        self.g("branch", "backup/main-copy")
        rc, rep, _ = self.run_tool()
        self.assertEqual(rc, 0, rep["problems"])
        states = {b["name"]: b["state"] for b in rep["branches"]}
        self.assertEqual(states["backup/main-copy"], "no upstream")

    def test_dirty_tree_warns_and_can_fail(self):
        (self.repo / "README.md").write_text("changed\n")
        (self.repo / "new.txt").write_text("n\n")
        rc, rep, _ = self.run_tool()
        self.assertEqual(rc, 0)
        self.assertEqual(rep["dirty_tracked"], ["README.md"])
        self.assertEqual(rep["untracked"], ["new.txt"])
        rc, _, _ = self.run_tool(None, "--fail-on-dirty")
        self.assertEqual(rc, 1)

    def test_stash_counted(self):
        (self.repo / "README.md").write_text("wip\n")
        self.g("stash", "-q")
        rc, rep, _ = self.run_tool()
        self.assertEqual(rep["stashes"], 1)
        self.assertIn("stash", " ".join(rep["warnings"]))

    def test_detached_head_with_orphan_commit_fails(self):
        self.g("checkout", "-q", "--detach")
        self.commit("orphan.txt", "o\n", "orphan")
        rc, rep, _ = self.run_tool()
        self.assertEqual(rc, 1)
        self.assertTrue(rep["detached"])
        self.assertEqual(rep["detached_unique_commits"], 1)

    def test_no_remote_at_all_means_everything_is_at_risk(self):
        solo = self.base / "solo"
        self.sh("git", "init", "-q", "-b", "master", str(solo))
        (solo / "a.txt").write_text("a\n")
        self.sh("git", "-C", str(solo), "add", "a.txt")
        self.sh("git", "-C", str(solo), "commit", "-q", "-m", "a")
        rc, rep, _ = self.run_tool(solo)
        self.assertEqual(rc, 1)
        self.assertEqual(rep["at_risk"], ["master"])
        self.assertIn("no remote-tracking refs", " ".join(rep["warnings"]))

    def test_broken_git_dir_like_the_clubsite_deploy_tree(self):
        broken = self.base / "clubsite"
        (broken / ".git").mkdir(parents=True)
        (broken / ".git" / "config").write_text("[core]\n")
        (broken / ".git" / "ORIG_HEAD").write_text("0" * 40 + "\n")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = gh.main([str(broken)])
        self.assertEqual(rc, 1)
        self.assertIn("BROKEN", out.getvalue())
        self.assertIn("not a working copy", out.getvalue())

    def test_not_a_repo_and_subdirectory_exit_two(self):
        plain = self.base / "plain"
        plain.mkdir()
        rc, _, err = self.run_tool(plain)
        self.assertEqual(rc, 2)
        self.assertIn("not a git repository", err)
        sub = self.repo / "sub"
        sub.mkdir()
        (sub / ".git").mkdir()
        rc, _, err = self.run_tool(sub)
        self.assertNotEqual(rc, 0)

    def test_tool_is_read_only(self):
        self.g("checkout", "-q", "-b", "feat/x")
        self.commit("x.txt", "x\n", "x")
        (self.repo / "README.md").write_text("dirty\n")
        git_dir = self.repo / ".git"
        before = {p: p.stat().st_mtime_ns for p in git_dir.rglob("*") if p.is_file()}
        self.run_tool()
        self.run_tool()
        after = {p: p.stat().st_mtime_ns for p in git_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_markdown_render_has_push_commands(self):
        self.g("checkout", "-q", "-b", "feat/y")
        self.commit("y.txt", "y\n", "y")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = gh.main([str(self.repo)])
        self.assertEqual(rc, 1)
        self.assertIn("Verdict: **AT RISK**", out.getvalue())
        self.assertIn("push -u origin feat/y", out.getvalue())
        self.assertNotIn("--force", out.getvalue().replace("never --force", ""))


if __name__ == "__main__":
    unittest.main()
