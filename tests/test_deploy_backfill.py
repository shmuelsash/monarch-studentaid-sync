"""deploy/backfill_balances.py: rebuild carried-forward days from the real
balances around them. Numbers are the real Oct 28 - Nov 3 2026 outage."""

import importlib.util
from datetime import date, timedelta
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "backfill_balances", Path(__file__).resolve().parents[1] / "deploy" / "backfill_balances.py"
)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

D = date.fromisoformat


def _flat_gap() -> dict[date, float]:
    hist = {D("2026-10-27"): -9480.27, D("2026-10-28"): -9481.05}
    for i in range(1, 6):  # Oct 29 - Nov 2: carried forward
        hist[D("2026-10-28") + timedelta(days=i)] = -9481.05
    hist[D("2026-11-03")] = -9485.72
    hist[D("2026-11-04")] = -9485.72  # today, after the last real day: untouched
    return hist


def test_fills_the_gap_on_the_interest_line() -> None:
    real = {D("2026-10-27"), D("2026-10-28"), D("2026-11-03")}
    fixes = backfill.plan_fill(_flat_gap(), real, {}, D("2026-11-04"))
    assert sorted(fixes) == [D("2026-10-28") + timedelta(days=i) for i in range(1, 6)]
    # 4.67 of interest over 6 days = 0.778/day
    assert fixes[D("2026-10-29")] == -9481.83
    assert fixes[D("2026-11-02")] == -9484.94
    assert D("2026-11-04") not in fixes


def test_steps_on_a_payment_inside_the_gap() -> None:
    hist = {D("2026-10-28"): -1000.0, D("2026-10-29"): -1000.0, D("2026-10-30"): -1000.0, D("2026-10-31"): -902.0}
    real = {D("2026-10-28"), D("2026-10-31")}
    fixes = backfill.plan_fill(hist, real, {D("2026-10-30"): 100.0}, D("2026-11-01"))
    # Net of the 100 payment the balance drifted -2 over 3 days: -0.67/day,
    # then the payment lifts it by 100 on its own date.
    assert fixes[D("2026-10-29")] == -1000.67
    assert fixes[D("2026-10-30")] == -901.33


def test_nothing_to_do_on_a_normal_day() -> None:
    hist = {D("2026-11-02"): -10.0, D("2026-11-03"): -10.5}
    real = set(hist)
    assert backfill.plan_fill(hist, real, {}, D("2026-11-03")) == {}
