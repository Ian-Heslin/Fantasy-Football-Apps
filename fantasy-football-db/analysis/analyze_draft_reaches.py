#!/usr/bin/env python3
"""
analyze_draft_reaches.py -- does getting drafted significantly higher
than your pre-draft grade implied predict underperformance? And are some
teams/coaches more likely to "reach" at a position and have it work out
anyway (the Kyle Shanahan/WR question)?

Method:
  1. Within each draft year, rank every prospect with a combine grade by
     NGS draft_grade (best grade = rank 1).
  2. Match those graded prospects to actual draft_picks by normalized
     name + position (no shared ID between the two sources -- see
     load_draft_grades.py/load_draft_picks.py). Unmatched players are
     dropped, not guessed at.
  3. Re-rank the matched players by actual pick number (earliest pick =
     rank 1) within the same year.
  4. reach_score = grade_rank - actual_rank. Positive = drafted earlier
     than the grade implied (a reach); negative = fell further than the
     grade implied; 0 = drafted almost exactly where graded.
  5. Test whether reach_score predicts career outcome (w_av, games,
     probowls), controlling for draft slot -- comparing reaches only
     against other players taken in the same draft-position band, not
     the whole league (obviously round-1 picks outproduce round-7 picks
     regardless of whether either group "reached").

Attribution: team- and head-coach-level via coach_table (PFR-sourced,
2001-2025); GM-level via team_executives_season (Wikipedia-sourced via
Claude/Cowork, see load_team_executives.py -- this sandbox can't reach
Wikipedia directly, so that data was fetched outside it).

Outputs (analysis/ directory):
  draft_reach_player_level.csv   -- every matched player, one row each
  draft_reach_by_team.csv         -- team-level reach tendency + outcome
  draft_reach_by_coach.csv        -- HC-level reach tendency + outcome
  draft_reach_by_gm.csv           -- GM-level reach tendency + outcome
"""
import os
import re
import statistics
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Picks within this many slots of each other count as "the same band" for
# the outcome comparison -- wide enough to have real sample sizes per
# band, narrow enough that we're not comparing round 1 to round 5.
PICK_BAND_WIDTH = 32  # roughly one round

# draft_picks (nflverse-data's richer release) uses PFR-style team codes;
# coach_table (built earlier in this project) uses this project's standard
# nflverse codes. Without this normalization, every relocated/renamed
# franchise silently fails the (year, team) join against coach_table --
# confirmed for SF (Shanahan's team, stored as SFO in draft_picks).
TEAM_CODE_MAP = {
    "GNB": "GB",
    "KAN": "KC",
    "LAR": "LA",
    "RAM": "LA",
    "STL": "LA",
    "LVR": "LV",
    "OAK": "LV",
    "RAI": "LV",
    "NOR": "NO",
    "NWE": "NE",
    "PHO": "ARI",
    "SDG": "LAC",
    "SFO": "SF",
    "TAM": "TB",
}


def normalize_team(team):
    return TEAM_CODE_MAP.get(team, team)


def log(msg):
    print(f"[analyze_draft_reaches] {msg}")


def normalize_name(name):
    name = name.lower()
    name = re.sub(r"[.']", "", name)
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    name = re.sub(r"[^a-z ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def load_matched_players(conn):
    grades = conn.execute(
        "SELECT year, player_name, position, ngs_draft_grade FROM draft_prospect_grades "
        "WHERE ngs_draft_grade IS NOT NULL"
    ).fetchall()
    picks = conn.execute(
        "SELECT season, pick, team, player_name, position, w_av, games, probowls, allpro, seasons_started "
        "FROM draft_picks WHERE season >= 2006"
    ).fetchall()

    picks_by_year = {}
    for season, pick, team, name, pos, w_av, games, probowls, allpro, starts in picks:
        picks_by_year.setdefault(season, []).append({
            "pick": pick, "team": normalize_team(team), "name": name, "position": pos,
            "w_av": w_av, "games": games, "probowls": probowls,
            "allpro": allpro, "seasons_started": starts,
            "norm_name": normalize_name(name),
        })

    grades_by_year = {}
    for year, name, pos, grade in grades:
        grades_by_year.setdefault(year, []).append({
            "norm_name": normalize_name(name), "position": pos, "grade": grade,
        })

    matched = []
    for year in sorted(set(grades_by_year) & set(picks_by_year)):
        year_picks = picks_by_year[year]
        year_grades = grades_by_year[year]
        grade_index = {}
        for g in year_grades:
            grade_index.setdefault((g["norm_name"], g["position"]), g)

        year_matches = []
        for p in year_picks:
            g = grade_index.get((p["norm_name"], p["position"]))
            if g is None:
                continue
            year_matches.append({**p, "grade": g["grade"], "year": year})

        if not year_matches:
            continue

        # rank by grade (best first) and by actual pick (earliest first),
        # among just this year's matched players
        by_grade = sorted(year_matches, key=lambda r: -r["grade"])
        for i, r in enumerate(by_grade, start=1):
            r["grade_rank"] = i
        by_pick = sorted(year_matches, key=lambda r: r["pick"])
        for i, r in enumerate(by_pick, start=1):
            r["actual_rank"] = i
        for r in year_matches:
            r["reach_score"] = r["grade_rank"] - r["actual_rank"]

        matched.extend(year_matches)

    return matched


def band_adjusted_outcome(matched):
    """For each player, the average w_av of others in the same year +/-
    PICK_BAND_WIDTH picks (excluding the player themselves), so "did this
    reach underperform" compares against realistic peers, not the whole
    league. Players with no w_av (e.g. never played) count as 0, not
    excluded -- that's a real outcome (a reach who never made the team),
    not missing data."""
    by_year = {}
    for r in matched:
        by_year.setdefault(r["year"], []).append(r)

    for year, rows in by_year.items():
        for r in rows:
            peers = [
                x["w_av"] or 0.0 for x in rows
                if x is not r and abs(x["pick"] - r["pick"]) <= PICK_BAND_WIDTH
            ]
            r["peer_avg_av"] = statistics.mean(peers) if peers else None
            r["av_vs_peers"] = (r["w_av"] or 0.0) - r["peer_avg_av"] if r["peer_avg_av"] is not None else None
    return matched


def write_csv(path, rows, columns):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in columns})


def correlation(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 10:
        return None
    xs2, ys2 = zip(*pairs)
    sx, sy = statistics.pstdev(xs2), statistics.pstdev(ys2)
    if sx == 0 or sy == 0:
        return None
    mx, my = statistics.mean(xs2), statistics.mean(ys2)
    cov = sum((x - mx) * (y - my) for x, y in pairs) / len(pairs)
    return cov / (sx * sy)


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    matched = load_matched_players(conn)
    log(f"matched {len(matched)} drafted players to a pre-draft grade "
        f"(years {min(r['year'] for r in matched)}-{max(r['year'] for r in matched)})")

    matched = band_adjusted_outcome(matched)

    player_cols = ["year", "team", "name", "position", "pick", "grade", "grade_rank",
                   "actual_rank", "reach_score", "w_av", "games", "probowls", "allpro",
                   "seasons_started", "peer_avg_av", "av_vs_peers"]
    write_csv(os.path.join(OUT_DIR, "draft_reach_player_level.csv"), matched, player_cols)

    # ---- headline finding: does reach_score predict av_vs_peers? ----
    reach_scores = [r["reach_score"] for r in matched]
    av_vs_peers = [r["av_vs_peers"] for r in matched]
    corr = correlation(reach_scores, av_vs_peers)
    log(f"correlation(reach_score, career AV vs. same-draft-slot peers): {corr}")
    log("(negative = bigger reaches tend to underperform their draft-slot peers; "
        "near zero/positive = reaches don't systematically underperform)")

    big_reaches = [r for r in matched if r["reach_score"] >= 32 and r["av_vs_peers"] is not None]
    non_reaches = [r for r in matched if r["reach_score"] <= 0 and r["av_vs_peers"] is not None]
    if big_reaches and non_reaches:
        log(f"big reaches (reach_score >= 32, n={len(big_reaches)}): "
            f"avg AV vs. peers = {statistics.mean(r['av_vs_peers'] for r in big_reaches):.2f}")
        log(f"matched-or-fell (reach_score <= 0, n={len(non_reaches)}): "
            f"avg AV vs. peers = {statistics.mean(r['av_vs_peers'] for r in non_reaches):.2f}")

    # ---- team-level reach tendency ----
    by_team = {}
    for r in matched:
        by_team.setdefault(r["team"], []).append(r)
    team_rows = []
    for team, rows in by_team.items():
        reaches = [r for r in rows if r["reach_score"] > 0]
        team_rows.append({
            "team": team,
            "n_picks": len(rows),
            "avg_reach_score": statistics.mean(r["reach_score"] for r in rows),
            "n_reaches": len(reaches),
            "avg_av_vs_peers_on_reaches": (
                statistics.mean(r["av_vs_peers"] for r in reaches if r["av_vs_peers"] is not None)
                if any(r["av_vs_peers"] is not None for r in reaches) else None
            ),
        })
    team_rows.sort(key=lambda r: r["avg_reach_score"], reverse=True)
    write_csv(
        os.path.join(OUT_DIR, "draft_reach_by_team.csv"), team_rows,
        ["team", "n_picks", "avg_reach_score", "n_reaches", "avg_av_vs_peers_on_reaches"],
    )

    # ---- attribution rows shared by HC and GM breakdowns ----
    def attribution_rows(matched, by_team_season, key_label, min_picks=5):
        grouped = {}
        for r in matched:
            person = by_team_season.get((r["year"], r["team"]))
            if person is None:
                continue
            grouped.setdefault(person, []).append(r)

        rows = []
        for person, rows_for_person in grouped.items():
            if len(rows_for_person) < min_picks:
                continue  # too few picks under this person to say anything
            reaches = [r for r in rows_for_person if r["reach_score"] > 0]
            rows.append({
                key_label: person,
                "n_picks": len(rows_for_person),
                "avg_reach_score": statistics.mean(r["reach_score"] for r in rows_for_person),
                "n_reaches": len(reaches),
                "avg_av_vs_peers_on_reaches": (
                    statistics.mean(r["av_vs_peers"] for r in reaches if r["av_vs_peers"] is not None)
                    if any(r["av_vs_peers"] is not None for r in reaches) else None
                ),
            })
        rows.sort(key=lambda r: r["avg_reach_score"], reverse=True)
        return rows

    # ---- HC-level reach tendency (via coach_table) ----
    hc_rows_raw = conn.execute(
        "SELECT season, team, coach_name FROM coach_table WHERE role = 'HC'"
    ).fetchall()
    hc_by_team_season = {(season, team): coach for season, team, coach in hc_rows_raw}

    coach_rows = attribution_rows(matched, hc_by_team_season, "coach")
    write_csv(
        os.path.join(OUT_DIR, "draft_reach_by_coach.csv"), coach_rows,
        ["coach", "n_picks", "avg_reach_score", "n_reaches", "avg_av_vs_peers_on_reaches"],
    )

    # ---- GM-level reach tendency (via team_executives_season) ----
    gm_rows_raw = conn.execute(
        "SELECT season, team, general_manager FROM team_executives_season WHERE general_manager IS NOT NULL"
    ).fetchall()
    gm_by_team_season = {(season, team): gm for season, team, gm in gm_rows_raw}

    gm_rows = attribution_rows(matched, gm_by_team_season, "gm")
    write_csv(
        os.path.join(OUT_DIR, "draft_reach_by_gm.csv"), gm_rows,
        ["gm", "n_picks", "avg_reach_score", "n_reaches", "avg_av_vs_peers_on_reaches"],
    )

    # ---- the Shanahan/WR question specifically, if the data supports it ----
    shanahan_wr = [
        r for r in matched
        if r["position"] == "WR" and hc_by_team_season.get((r["year"], r["team"])) == "Kyle Shanahan"
    ]
    if shanahan_wr:
        avg_reach = statistics.mean(r["reach_score"] for r in shanahan_wr)
        avg_av = statistics.mean(r["av_vs_peers"] for r in shanahan_wr if r["av_vs_peers"] is not None) \
            if any(r["av_vs_peers"] is not None for r in shanahan_wr) else None
        log(f"Kyle Shanahan WR picks matched (n={len(shanahan_wr)}): "
            f"avg reach_score={avg_reach:.1f}, avg AV vs. peers={avg_av}")
    else:
        log("No Kyle Shanahan WR picks found in the matched set -- check coach_table's "
            "name spelling for Shanahan, or that his team-seasons are covered.")

    conn.close()
    log(f"wrote draft_reach_player_level.csv, draft_reach_by_team.csv, "
        f"draft_reach_by_coach.csv, draft_reach_by_gm.csv to {OUT_DIR}")
    log("done.")


if __name__ == "__main__":
    main()
