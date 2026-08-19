import json, csv

with open("/home/claude/sleeper/player_crosswalk.json") as f:
    crosswalk = json.load(f)
with open("/home/claude/sleeper/arbitrage_signal.json") as f:
    arb = json.load(f)
with open("/home/claude/sleeper/leagues_summary.json") as f:
    leagues = json.load(f)["leagues"]

NFL_TEAMS = {"ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU","IND",
             "JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB","TEN","WAS"}

def is_superflex(league):
    return "SUPER_FLEX" in league.get("format_notes", "")

def label(gap):
    if gap is None:
        return "no redraft/dynasty ECR overlap"
    if gap >= 0.15:
        return "BUY-LOW / HOLD (dynasty market believes in him more than current production)"
    if gap <= -0.15:
        return "SELL-HIGH (current production is outrunning his long-term dynasty price)"
    return "fairly priced"

csv_rows = [("league","player","position","team","age","dynasty_value","dyn_percentile","redraft_percentile","gap","signal")]
report = []

for lg in leagues:
    sf = is_superflex(lg)
    value_key = "value_2qb" if sf else "value_1qb"
    gap_key = "gap_sf" if sf else "gap_1qb"
    dyn_key = "dyn_pctile_sf" if sf else "dyn_pctile_1qb"
    red_key = "red_pctile_sf" if sf else "red_pctile_1qb"
    name = lg["name"] or "(unnamed league)"
    report.append(f"\n=== {name} | {'Superflex' if sf else '1QB'} ===")

    rows = []
    for pid in lg["my_player_ids"]:
        if pid in NFL_TEAMS or pid == "DEF":
            continue
        e = crosswalk.get(pid)
        a = arb.get(pid, {})
        if not e:
            continue
        gap = a.get(gap_key)
        rows.append({
            "name": e["name"], "pos": e["position"], "team": e["team"], "age": e.get("age"),
            "value": e.get(value_key), "dyn_p": a.get(dyn_key), "red_p": a.get(red_key),
            "gap": gap, "label": label(gap),
        })

    # sort: biggest buy-low gap first, then biggest sell-high
    rows.sort(key=lambda r: (r["gap"] is None, -(r["gap"] or 0)))

    for r in rows:
        gapstr = f"{r['gap']:+.2f}" if r["gap"] is not None else "n/a"
        vstr = f"{float(r['value']):,.0f}" if r["value"] not in (None,"","NA") else "n/a"
        report.append(f"  {r['name']:<26} {r['pos']:<3} {r['team']:<4} age {str(r['age']):<5} value={vstr:<8} gap={gapstr:<6} {r['label']}")
        csv_rows.append((name, r["name"], r["pos"], r["team"], r["age"], r["value"], r["dyn_p"], r["red_p"], r["gap"], r["label"]))

with open("/home/claude/sleeper/trade_signals.csv","w",newline="") as f:
    csv.writer(f).writerows(csv_rows)

print("\n".join(report))
