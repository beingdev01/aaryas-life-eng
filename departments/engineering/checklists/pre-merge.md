# Pre-merge checklist

Run by the integrator (opencode-1) before a feature branch is merged, and checked again
by the CEO. Merging to main of /home/ubuntu/clubsite-git is a production deploy:
auto-deploy ships origin/main within 3 minutes.

## The work
- [ ] The engine run ended `RESULT: DONE`; RUN_REPORT.md shows every acceptance check
      passed and total reported cost 0.
- [ ] The latest review is APPROVE from a reviewer who built nothing in this change, and
      `tools/review_lint.py` passes on it.
- [ ] No critical or high finding is open; deferred medium or low findings are listed on
      the issue with a reason.

## The branch
- [ ] `git status` is clean; `git branch --show-current` is the feature branch.
- [ ] `git pull --ff-only` on main succeeded; the feature branch is rebased or merged on it
      and the tests pass again after that.
- [ ] `python3 tools/git_hygiene.py <repo>` exits 0: the feature branch is pushed and
      nothing exists only on this disk.
- [ ] `git diff --stat main...<branch>` touches only the files the plan owned.
- [ ] No secrets in the diff: `git diff main...<branch> | grep -nEi 'api[_-]?key|secret|password|BEGIN .*PRIVATE KEY'`
      prints nothing.
- [ ] A safety branch exists for anything that will be rewritten:
      `git branch backup/<branch>-<yyyymmdd> && git push origin backup/<branch>-<yyyymmdd>`.

## The merge
- [ ] Merge with a normal merge or fast-forward; never `--force` to main.
- [ ] For clubsite-git: the CEO has approved the merge on the issue, because it deploys.
- [ ] After merge: `git push origin main`, then for clubsite-git watch
      `tail -n 5 /home/ubuntu/auto-deploy.log` for `deployed <sha> OK` and curl
      https://codescriet.dev/ for 200.
- [ ] The issue gets a receipt comment: merge commit sha, branch, and the verification output.
