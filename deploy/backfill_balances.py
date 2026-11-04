"""Fill in true daily loan balances for days the sync did not run.

Monarch carries a manual account's last balance forward, so a day the sync
missed (runner offline, portal down) shows yesterday's number, and the next
successful run lands as one jump. Loans accrue interest daily, so the real
value of a missed day is recoverable: it lies on the line between the two
real balances around the gap, stepped on any payment date inside it.

Deploy-layer, not upstream: it runs after every successful sync in the same
container (same .env, same secrets, same Monarch login chain, which re-signs in
with email/password/MFA on its own when the saved session has expired). On a
normal day there is no gap and it changes nothing.

Safety: Monarch's balance-history upload takes the account's whole history,
so the full history is saved to data/ before any upload, the upload is read
back and compared, and a mismatch restores the saved copy and fails the step.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("backfill_balances")

# Monarch dates a balance change by the user's day; the sync's run times are UTC.
LOCAL_TZ = ZoneInfo(os.getenv("BACKFILL_TZ", "America/New_York"))
# Only look this far back: older history is settled and never re-written.
WINDOW_DAYS = int(os.getenv("BACKFILL_WINDOW_DAYS", "45"))
DATA = Path("data")
DRY_RUN = os.getenv("BACKFILL_DRY_RUN", "") == "1"  # log the plan, write nothing


def real_days(db_path: Path) -> set[date]:
    """Local dates on which a sync run finished OK (so its balance is real)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute("SELECT finished_at FROM runs WHERE ok = 1 AND finished_at IS NOT NULL")
    days = set()
    for (ts,) in rows:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days.add(dt.astimezone(LOCAL_TZ).date())
    con.close()
    return days


def payments(db_path: Path) -> dict[str, dict[date, float]]:
    """group -> {payment date: dollars applied}, from the sync's own ledger."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out: dict[str, dict[date, float]] = {}
    for day, group, cents in con.execute(
        "SELECT payment_date, group_code, total_applied_cents FROM processed_payment_allocations"
    ):
        by_day = out.setdefault(group, {})
        d = date.fromisoformat(day[:10])
        by_day[d] = by_day.get(d, 0.0) + cents / 100
    con.close()
    return out


def plan_fill(
    history: dict[date, float],
    real: set[date],
    paid: dict[date, float],
    today: date,
) -> dict[date, float]:
    """{day: corrected signed balance} for every carried-forward day that sits
    between two real balances. Balances are signed (a loan is negative), so a
    payment moves the balance up by the amount applied."""
    start = today - timedelta(days=WINDOW_DAYS)
    anchors = sorted(d for d in real if d in history and start <= d <= today)
    fixes: dict[date, float] = {}
    for a, b in zip(anchors, anchors[1:]):
        span = (b - a).days
        if span < 2:
            continue
        paid_in = sum(v for d, v in paid.items() if a < d <= b)
        slope = (history[b] - history[a] - paid_in) / span
        for i in range(1, span):
            d = a + timedelta(days=i)
            if d not in history:
                continue
            target = round(
                history[a] + slope * i + sum(v for p, v in paid.items() if a < p <= d), 2
            )
            if abs(target - history[d]) >= 0.01:
                fixes[d] = target
    return fixes


async def backfill_account(mm, account_id: str, real: set[date], paid: dict[date, float]) -> int:
    from monarchmoney.monarchmoney import BalanceHistoryRow

    snaps = await mm.get_account_history(int(account_id))
    history = {date.fromisoformat(s["date"]): float(s["signedBalance"]) for s in snaps}
    name = snaps[-1].get("accountName", "") if snaps else ""
    fixes = plan_fill(history, real, paid, datetime.now(LOCAL_TZ).date())
    if not fixes:
        logger.info("%s: no missed days to fill", name or account_id)
        return 0

    backup = DATA / f"balance_history_backup_{account_id}_{datetime.now():%Y%m%d_%H%M%S}.json"
    backup.write_text(json.dumps(snaps))
    for d, v in sorted(fixes.items()):
        logger.info("%s: %s %.2f -> %.2f", name, d, history[d], v)
    if DRY_RUN:
        return len(fixes)

    def rows(values: dict[date, float]) -> list:
        return [
            BalanceHistoryRow(date=datetime.combine(d, datetime.min.time()), amount=v, account_name=name)
            for d, v in sorted(values.items())
        ]

    wanted = {**history, **fixes}
    if not await mm.upload_account_balance_history(account_id, rows(wanted)):
        raise RuntimeError(f"{name}: Monarch did not finish processing the balance upload")

    after = {
        date.fromisoformat(s["date"]): float(s["signedBalance"])
        for s in await mm.get_account_history(int(account_id))
    }
    bad = [d for d, v in wanted.items() if abs(after.get(d, float("nan")) - v) >= 0.01]
    if bad:
        logger.error("%s: upload read back wrong on %d day(s) (first %s); restoring %s", name, len(bad), bad[0], backup)
        await mm.upload_account_balance_history(account_id, rows(history))
        raise RuntimeError(f"{name}: balance upload did not stick; history restored from {backup}")
    logger.info("%s: filled %d missed day(s)", name, len(fixes))
    return len(fixes)


async def main() -> int:
    sys.path.insert(0, "/app/src")
    from studentaid_monarch_sync.config import load_config
    from studentaid_monarch_sync.monarch.client import MonarchClient
    from studentaid_monarch_sync.monarch.loan_accounts import default_mapping_path, load_loan_account_mapping

    cfg = load_config("config.yaml")
    db = Path(cfg.state.db_path)
    mapping = load_loan_account_mapping(default_mapping_path(cfg.servicer.provider or "servicer"))
    client = MonarchClient(
        email=cfg.monarch.email,
        password=cfg.monarch.password,
        cookie_string=cfg.monarch.cookie_string,
        token=cfg.monarch.token,
        mfa_secret=cfg.monarch.mfa_secret,
        session_file=cfg.monarch.session_file,
    )
    await client.login()  # saved session, else a fresh email/password/MFA sign-in
    real, paid = real_days(db), payments(db)
    total = 0
    for group, m in mapping.items():
        total += await backfill_account(client._mm, m.account_id, real, paid.get(group, {}))
    logger.info("Backfill done: %d day(s) filled across %d account(s)", total, len(mapping))
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:
        # One ::error:: line so the dashboard card and the phone alert say why.
        print(f"::error::Balance backfill failed: {e}", flush=True)
        logger.exception("backfill failed")
        sys.exit(1)
