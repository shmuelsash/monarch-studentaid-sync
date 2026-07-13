# Deploy / CI (fork-specific)

This fork deploys via a self-hosted GitHub Actions runner on the TrueNAS box
(see `.github/workflows/daily-sync.yml`), not a TrueNAS cron job. One workflow
drives both deployments (`nelnet-sync-shmuel` and `edfinancial-sync-shana`) via
a matrix — it pulls the deployed dir's code, rebuilds the image, and runs the
sync with `docker compose run --rm`.

Kept out of `README.md` on purpose — that file tracks upstream
(mattebad/monarch-studentaid-sync), so it stays untouched to survive merges.

## Adding a new sync job (new matrix entry, or a new person)

If you're adding another `person:` entry to the matrix, or copying
`daily-sync.yml` as a template for an unrelated repo, keep the **"Remove the
compose network"** step at the end. `docker compose run --rm` only removes the
container — it leaves the project's bridge network behind every run. Skip
that step and it's one more orphaned Docker network piling up on the TrueNAS
box forever (there were 39 of them, across all the sync jobs, before this was
added) — exactly the kind of clutter that causes intermittent container
networking failures.
