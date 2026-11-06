"""Decide whether this scheduled run should download today's problem, and when.

The workflow runs this hourly. Every run on a given day derives the same random
target time (8:00-11:59 AM US Eastern, following daylight saving) from the date,
so exactly one run goes ahead:

  * today's problem already committed     -> skip
  * target is more than ~an hour away     -> skip (a later run handles it)
  * target is within the next hour        -> sleep until it, then go
  * target has passed but nothing yet     -> go now (an earlier run was missed)

Prints the decision and writes go=true/false to $GITHUB_OUTPUT.
Test locally with:  python random_time.py --now 2026-11-07T09:05-05:00 --dry-run
"""
from __future__ import annotations

import argparse
import os
import random
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
START_HOUR, END_HOUR = 8, 12  # window is [8:00, 12:00) local time
MAX_WAIT = timedelta(minutes=65)  # checks are hourly; a little slack for late starts
PROBLEMS = Path(__file__).resolve().parents[2] / "problems"


def target_for(day: date) -> datetime:
    rng = random.Random(f"leetcode-daily-{day.isoformat()}")  # same result in every run that day
    offset = timedelta(seconds=rng.randrange((END_HOUR - START_HOUR) * 3600))
    return datetime(day.year, day.month, day.day, START_HOUR, tzinfo=TZ) + offset


def already_done(now: datetime) -> bool:
    # daily.py names folders by the UTC date, which is LeetCode's day boundary.
    utc_day = now.astimezone(timezone.utc).date().isoformat()
    return any(p.is_dir() for p in PROBLEMS.glob(f"{utc_day}_*"))


def decide(now: datetime) -> tuple[float | None, str]:
    """Return (seconds to wait, reason); None means skip this run."""
    if already_done(now):
        return None, "today's problem is already committed"
    target = target_for(now.astimezone(TZ).date())
    when = target.strftime("%I:%M:%S %p %Z").lstrip("0")
    wait = target - now
    if wait <= timedelta(0):
        return 0.0, f"target {when} has passed and nothing is committed yet; going now"
    if wait <= MAX_WAIT:
        return wait.total_seconds(), f"waiting {wait} for target {when}"
    return None, f"target {when} is {wait} away; a later run will handle it"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", type=datetime.fromisoformat, help="pretend it's this time (ISO, with offset)")
    ap.add_argument("--dry-run", action="store_true", help="don't sleep")
    args = ap.parse_args()

    now = args.now or datetime.now(timezone.utc)
    wait, reason = decide(now)
    print(reason)
    if wait and not args.dry_run:
        time.sleep(wait)
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"go={'true' if wait is not None else 'false'}\n")


if __name__ == "__main__":
    main()
