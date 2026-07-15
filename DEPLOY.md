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

## Transient portal flakes: retried at the deploy layer, not in `src/`

The "Run sync" step retries the whole `docker compose run` once (60s apart)
before failing the job. This exists because the portal login occasionally
hits a one-off render hiccup — e.g. 2026-07-15's Nelnet run failed with
`Could not find clickable element for any of: ('Sign in', ...)`, and a plain
manual rerun of the exact same code succeeded immediately. That's a signature
of a transient flake, not a broken selector — worth a workflow-level retry,
not worth patching `src/` (see above: never diverge from upstream).

If the *same* failure repeats across multiple days, that's no longer a flake
retry can paper over — it means the portal actually changed and needs a real
selector fix upstream (PR to mattebad, same process as the EdFinancial pin).

## Adding a new sync job (new matrix entry, or a new person)

If you're adding another `person:` entry to the matrix, or copying
`daily-sync.yml` as a template for an unrelated repo, keep the **"Remove the
compose network"** step at the end. `docker compose run --rm` only removes the
container — it leaves the project's bridge network behind every run. Skip
that step and it's one more orphaned Docker network piling up on the TrueNAS
box forever (there were 39 of them, across all the sync jobs, before this was
added) — exactly the kind of clutter that causes intermittent container
networking failures.
