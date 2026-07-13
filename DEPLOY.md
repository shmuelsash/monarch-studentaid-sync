# Deploy / CI (fork-specific)

This fork deploys via a self-hosted GitHub Actions runner on the TrueNAS box
(see `.github/workflows/daily-sync.yml`), not a TrueNAS cron job. One workflow
drives both deployments (`nelnet-sync-shmuel` and `edfinancial-sync-shana`) via
a matrix — it pulls the deployed dir's code, rebuilds the image, and runs the
sync with `docker compose run --rm`.

Kept out of `README.md` on purpose — that file tracks upstream
(mattebad/monarch-studentaid-sync), so it stays untouched to survive merges.

## Why this fork exists (read before touching `src/`)

**This fork's only job is to host the files above.** It exists because a
GitHub self-hosted runner has to be registered to *some* repo and the workflow
YAML has to live in that repo's git history — not because we want to run code
that's different from mattebad's. `src/` on this fork's `main` must stay
byte-for-byte identical to `upstream/main`, forever. Check anytime with:

```bash
git diff --stat upstream/main origin/main   # should show CI/deploy files only, never src/
```

The deploy matrix in `daily-sync.yml` proves this in practice: Nelnet's `ref`
is `origin/main` (mattebad's upstream, pulled fresh every run — his fixes
reach the box automatically, same day). EdFinancial is temporarily pinned to
`fork/fix/edfinancial-cookieyes-modals` **only** because of a real bug fix
(mattebad/monarch-studentaid-sync#18) that hasn't merged upstream yet.

**If you find or need to fix a bug in the app itself: open a PR against
`mattebad/monarch-studentaid-sync`, not a commit here.** Push the fix to a
branch on this fork, point the matrix's `ref:` at `fork/<branch-name>` to run
it in production while the PR is in review, and switch the `ref:` back to
`origin/main` the moment it merges. Never hand-edit `src/` on this fork's
`main` — that's exactly the drift this setup is built to avoid.

## Adding a new sync job (new matrix entry, or a new person)

If you're adding another `person:` entry to the matrix, or copying
`daily-sync.yml` as a template for an unrelated repo, keep the **"Remove the
compose network"** step at the end. `docker compose run --rm` only removes the
container — it leaves the project's bridge network behind every run. Skip
that step and it's one more orphaned Docker network piling up on the TrueNAS
box forever (there were 39 of them, across all the sync jobs, before this was
added) — exactly the kind of clutter that causes intermittent container
networking failures.
