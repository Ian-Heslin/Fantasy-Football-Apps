#!/usr/bin/env python3
"""
promote_user.py -- sets a user's tier directly in app.db. Only needed to
bootstrap the very first admin (sign up normally on the site, then run
this once) -- after that, admins can change tiers from /admin/users in
the web app itself.

Usage:
    python3 scripts/promote_user.py <username> admin
    python3 scripts/promote_user.py <username> fantasy
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_PATH = os.path.join(ROOT, "data", "app.db")
VALID_TIERS = ("games", "fantasy", "admin")


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in VALID_TIERS:
        print(f"Usage: python3 scripts/promote_user.py <username> <{'|'.join(VALID_TIERS)}>")
        sys.exit(1)

    username, tier = sys.argv[1], sys.argv[2]
    conn = sqlite3.connect(SQLITE_PATH)
    cur = conn.execute("UPDATE users SET tier = ? WHERE username = ?", (tier, username))
    conn.commit()
    if cur.rowcount == 0:
        print(f"No user named '{username}' -- sign up on the site first.")
        sys.exit(1)
    print(f"'{username}' is now tier '{tier}'.")
    conn.close()


if __name__ == "__main__":
    main()
