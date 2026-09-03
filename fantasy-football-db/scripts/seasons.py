"""Which NFL season it is, derived rather than hardcoded.

Several loaders and model builders used to carry their own `SEASON =
2026` / `LATEST_SEASON = 2025` / `LAST_COMPLETE_SEASON = 2025` constant.
Each was correct on the day it was written and each was an annual edit
that fails *silently*: once the year rolls over, a loader keeps pulling
a finished season, the table's max(season) never moves, and the web app
serves last year's data with no error at any layer.

Every script that needs a season imports from here and takes a
`--season` override for backfills. Scripts are run as
`python3 scripts/<name>.py` from the repo root, which puts scripts/ on
sys.path, so `from seasons import current_season` resolves.
"""
from datetime import date

# nflverse's play-by-play coverage starts here; nothing derives this.
EARLIEST_PBP_SEASON = 1999


def current_season(today=None):
    """The NFL season a given date belongs to.

    A season is named for the calendar year it starts in and runs
    September through early February, so January and February belong to
    the *previous* year's season. March through August is the offseason,
    which counts as the upcoming season -- that's when next year's
    schedule is published, which is what the schedule loaders want.
    """
    today = today or date.today()
    return today.year - 1 if today.month <= 2 else today.year


def last_complete_season(today=None):
    """The most recent season safe to treat as finished.

    Always current_season() - 1. That holds in all three cases: during
    the season it's in progress, in the offseason it hasn't started, and
    in January/February it's down to the playoffs. The one date range
    this is conservative about is the fortnight between the Super Bowl
    and the end of February, when the named season really is complete --
    deliberately, because model builders are the caller and training on
    a season whose data is still settling skews every fitted coefficient
    toward whoever started fast. Pass an explicit --season to override.
    """
    return current_season(today) - 1
