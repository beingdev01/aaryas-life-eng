# Git and shared-working-copy discipline

## Why
In the shared clone /home/ubuntu/clubsite-git, `feat/cert-templates-api` was reset to
origin/main while checked out on 19 Oct and twice more on 20 Oct 2026, dropping seven
reviewed commits (+2880 lines). It had never been pushed, and survived only through
`backup/cert-templates-20261019` and the reflog (AAR-116 receipt).

## Rules
1. Before work in a shared repo: `git status` clean, `git branch --show-current` is the
   branch you expect, `git pull --ff-only`. Not a fast-forward: stop and report; never
   merge or reset to make it one.
2. Work on a feature branch. Commit after each completed part, naming part and issue:
   `feat(certs): roster import (AAR-201 part 2)`.
3. Push at once: `git push -u origin <branch>` after the first commit, `git push` after each
   later one. Unpushed work is one reset from gone.
4. Never force-push main. On your own feature branch only `--force-with-lease`.
5. Never `reset --hard`, `checkout -- .`, `clean -f` or `stash drop` in a shared clone.
   Before anything destructive: `git branch backup/<branch>-<yyyymmdd>`, and push it.
6. /home/ubuntu/clubsite is the live deploy target; its .git holds only config and
   ORIG_HEAD. Never commit, pull or reset there.
7. Edit /home/ubuntu/clubsite-git only when the task names it. auto-deploy ships
   origin/main every 3 minutes: a push to main is a production deploy.

## Gate
`python3 tools/git_hygiene.py <repo>` is read-only and exits 1 while any branch has commits
on no remote or .git is broken. Add it to the acceptance of any repo task.
