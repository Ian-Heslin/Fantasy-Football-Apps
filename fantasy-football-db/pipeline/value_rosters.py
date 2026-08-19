import json

with open("/home/claude/sleeper/player_crosswalk.json") as f:
    crosswalk = json.load(f)

with open("/home/claude/sleeper/leagues_summary.json") as f:
    leagues = json.load(f)["leagues"]

NFL_TEAMS = {"ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU","IND",
             "JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB","TEN","WAS"}

SUPERFLEX_LEAGUES = {"Quarantine Dynasty", None, "D - 1"}  # TBD league name is None; also flag by roster_positions if available

def is_superflex(league):
    return "SUPER_FLEX" in league.get("format_notes", "")

report_lines = []
csv_rows = [("league","player","position","team","dynasty_value","ecr_overall","ecr_position","age")]

for lg in leagues:
    sf = is_superflex(lg)
    value_key = "value_2qb" if sf else "value_1qb"
    ecr_key = "ecr_2qb" if sf else "ecr_1qb"
    name = lg["name"] or "(unnamed league)"
    report_lines.append(f"\n=== {name} ({lg['league_id']}) | format: {'Superflex' if sf else '1QB'} | roster #{lg['my_roster_id']} ===")
    resolved = []
    unresolved = []
    for pid in lg["my_player_ids"]:
        if pid in NFL_TEAMS or pid == "DEF":
            resolved.append({"name": f"{pid} D/ST", "position":"DEF", "team":pid, "value": None, "ecr": None, "ecr_pos": None, "age": None})
            continue
        entry = crosswalk.get(pid)
        if not entry:
            unresolved.append(pid)
            continue
        resolved.append({
            "name": entry["name"], "position": entry["position"], "team": entry["team"],
            "value": entry.get(value_key), "ecr": entry.get(ecr_key), "ecr_pos": entry.get("ecr_pos"),
            "age": entry.get("age"),
        })

    def sortkey(p):
        v = p["value"]
        try:
            return -float(v)
        except (TypeError, ValueError):
            return 0
    resolved.sort(key=sortkey)

    total_value = sum(float(p["value"]) for p in resolved if p["value"] not in (None, "NA"))
    report_lines.append(f"Total resolved dynasty value ({value_key}): {total_value:,.0f}  |  players resolved: {len(resolved)}/{len(lg['my_player_ids'])}  |  unresolved IDs: {unresolved}")
    for p in resolved:
        v = p["value"]
        vstr = f"{float(v):,.0f}" if v not in (None,"NA") else "no market value (deep bench/FA)"
        report_lines.append(f"  {p['name']:<28} {p['position']:<4} {p['team']:<4} value={vstr}")
        csv_rows.append((name, p["name"], p["position"], p["team"], v or "", p["ecr"] or "", p["ecr_pos"] or "", p["age"] or ""))

with open("/home/claude/sleeper/my_rosters_valued.txt","w") as f:
    f.write("\n".join(report_lines))

import csv
with open("/home/claude/sleeper/my_rosters_valued.csv","w",newline="") as f:
    csv.writer(f).writerows(csv_rows)

print("\n".join(report_lines))
