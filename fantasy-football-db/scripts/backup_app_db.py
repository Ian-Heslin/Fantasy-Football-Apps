#!/usr/bin/env python3
"""
backup_app_db.py -- makes a timestamped copy of app.db into data/backups/,
then deletes backups older than KEEP_DAYS. Meant to run on a schedule
(see webapp/deploy/app-db-backup.timer) completely independent of git --
app.db holds live, continuously-written data (user accounts, Pick'em
picks/settings, roster links) with no other source of truth, so it needs
its own backup story regardless of anything else.

Uses sqlite3's online backup API (Connection.backup()), not a plain file
copy -- a plain copy can grab a half-written page if the app is writing
at that exact moment (WAL checkpoint, an in-progress transaction) and
produce a corrupt backup; the backup API is safe to run against a live,
in-use database.

Usage:
    python3 scripts/backup_app_db.py
    python3 scripts/backup_app_db.py --keep-days 60
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_PATH = os.path.join(ROOT, "data", "app.db")
BACKUP_DIR = os.path.join(ROOT, "data", "backups")
DEFAULT_KEEP_DAYS = 30


def log(msg):
    print(f"[backup_app_db] {msg}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS,
                         help=f"delete backups older than this many days (default {DEFAULT_KEEP_DAYS})")
    args = parser.parse_args()

    if not os.path.exists(SQLITE_PATH):
        log("app.db not found -- nothing to back up.")
        sys.exit(1)

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = os.path.join(BACKUP_DIR, f"app_{stamp}.db")
    # Write to a .tmp name and rename into place only once the copy has
    # been checked. Writing straight to the final name meant a run that
    # died partway (disk full, SD card hiccup) left a truncated file
    # sitting there under a perfectly normal-looking app_<stamp>.db name
    # -- indistinguishable from a good backup until the day you needed
    # to restore it, and counted as a keeper by the pruning below while
    # real backups aged out around it.
    temp_path = dest_path + ".tmp"

    src = sqlite3.connect(SQLITE_PATH)
    dest = sqlite3.connect(temp_path)
    try:
        with dest:
            src.backup(dest)
        # integrity_check reads every page of the copy; on a database
        # this size it's a few milliseconds, and it's the difference
        # between "a file exists" and "a file restores".
        result = dest.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"integrity check failed on the copy: {result}")
    except BaseException:
        dest.close()
        src.close()
        if os.path.exists(temp_path):
            os.remove(temp_path)
        log("backup FAILED -- partial copy removed, previous backups untouched.")
        raise
    dest.close()
    src.close()

    os.replace(temp_path, dest_path)
    log(f"backed up app.db -> {dest_path} ({os.path.getsize(dest_path)} bytes, integrity ok)")

    cutoff = datetime.now() - timedelta(days=args.keep_days)
    removed = 0
    for name in os.listdir(BACKUP_DIR):
        # .tmp files are never candidates -- a leftover one is debris
        # from a crashed run, not a backup whose age means anything.
        if not (name.startswith("app_") and name.endswith(".db")):
            continue
        path = os.path.join(BACKUP_DIR, name)
        if datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
            os.remove(path)
            removed += 1
    if removed:
        log(f"pruned {removed} backup(s) older than {args.keep_days} days")

    log("done.")


if __name__ == "__main__":
    main()
