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

The "Run sync" step retries the whole `docker compose run`, with two separate
budgets depending on how the attempt died.

**Anything that got as far as the portal: up to 3 attempts**, waiting 60s and
then 300s. This exists because the portal login occasionally hits a one-off
render hiccup — e.g. 2026-07-15's Nelnet run failed with
`Could not find clickable element for any of: ('Sign in', ...)`, and a plain
manual rerun of the exact same code succeeded immediately. That's a signature
of a transient flake, not a broken selector — worth a workflow-level retry,
not worth patching `src/` (see above: never diverge from upstream).

**Refused before the landing page loaded: up to 8 attempts**, waiting 30s,
60s, 120s, 240s, then 300s each (about 22 minutes at worst). This is
`Page.goto: net::ERR_CONNECTION_REFUSED` / `ERR_ADDRESS_UNREACHABLE` at the
servicer's root URL, and it is not rare: across every run from 2026-09-01 to
2026-10-06 it killed 49 of 129 attempts (38%), both servicers alike. Two things
about it shaped the budget:

- It is a coin flip per attempt, not an outage. The attempt right after a
  refusal was refused 16 times out of 38 — the same rate as any other attempt,
  and no better after a 300s wait than after 60s. With three flips a job loses
  about 1 time in 18, which is what 2026-09-21 (both jobs) and 2026-10-06
  (EdFinancial) were. With eight it is about 1 in 2,300.
- A refused attempt is nearly free. It is over in 3–20 seconds and never
  reaches a login form, so repeating it cannot move a servicer account toward
  a lockout. (It does repeat the Monarch preflight, which reuses the saved
  session.) A refusal on any deeper URL means a login already happened, so
  those are deliberately left on the 3-attempt budget.

This is a workaround for the symptom, not a cure. *Why* Chromium gets refused
four times in ten while a plain socket to the same address connects seconds
later is still not known — see "Reading a failed run" below. If the rate ever
climbs, eight attempts will start losing too, and the answer then is to find
the cause rather than raise the number again.

**A rejected login is not retried at all.** If the output names one — Monarch's
`Invalid email and password combination`, the portal's `rejected your User ID /
Password`, or any "account may be locked" wording — the step stops right there.
Those fail identically every time, and each extra attempt is one closer to the
lockout the app itself warns about. 2026-09-15's evening Nelnet pass spent both
its attempts, and a 60s wait, on a password Monarch had already refused. When
you see that error, refresh that job's credentials in the dashboard
(Sync → Credentials) and rerun; retrying as-is cannot help.

If the *same* failure repeats across multiple days, that's no longer a flake
retry can paper over — it means the portal actually changed and needs a real
selector fix upstream (PR to mattebad, same process as the EdFinancial pin).

## Reading a failed run

The "Network diagnostics (on failure)" step probes, at failure time, from both
sides of the boundary the sync actually crosses:

- **from the host** — the runner's own view, and
- **from inside the container**, on the compose bridge network, which is where
  `net::ERR_CONNECTION_REFUSED` is actually raised. A host that reaches the
  servicer while the container cannot is the orphaned-bridge-network problem
  described in the next section, not an upstream outage.

It probes this job's servicer (read from `SERVICER_PROVIDER`, or
`SERVICER_BASE_URL` when that is set, exactly as `config.py` resolves it),
Monarch, Gmail and the image registry — each on the port the app really uses,
so Gmail is checked on IMAPS 993 rather than 443. Only hostnames and IPs are
printed, never `.env` contents, and the step always exits 0 so it cannot mask
the failure it is describing.

## Adding a new sync job (new matrix entry, or a new person)

If you're adding another `person:` entry to the matrix, or copying
`daily-sync.yml` as a template for an unrelated repo, keep the **"Remove the
compose network"** step at the end. `docker compose run --rm` only removes the
container — it leaves the project's bridge network behind every run. Skip
that step and it's one more orphaned Docker network piling up on the TrueNAS
box forever (there were 39 of them, across all the sync jobs, before this was
added) — exactly the kind of clutter that causes intermittent container
networking failures.
