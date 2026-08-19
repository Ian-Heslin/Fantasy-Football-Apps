import csv, json

DP = "/home/claude/dynastyprocess-data/files"

# 1. Load latest ECR snapshot, pull out the 4 pages we need
pages = {
    "dynasty_1qb": "/nfl/rankings/dynasty-overall.php",
    "dynasty_sf": "/nfl/rankings/dynasty-superflex.php",
    "redraft_1qb": "/nfl/rankings/ppr-cheatsheets.php",
    "redraft_sf": "/nfl/rankings/ppr-superflex-cheatsheets.php",
}
by_page = {k: {} for k in pages}
pool_size = {k: 0 for k in pages}

with open(f"{DP}/db_fpecr_latest.csv") as f:
    for row in csv.DictReader(f):
        for key, page in pages.items():
            if row["fp_page"] == page:
                fp_id = row["id"]
                by_page[key][fp_id] = float(row["ecr"])
                pool_size[key] += 1

print("Pool sizes:", pool_size)

def percentile(key, fp_id):
    ecr = by_page[key].get(fp_id)
    if ecr is None:
        return None
    n = pool_size[key]
    return 1 - (ecr - 1) / (n - 1)

# 2. Load crosswalk (sleeper_id -> name/pos/team/fp_id/value)
with open("/home/claude/sleeper/player_crosswalk.json") as f:
    crosswalk = json.load(f)

# 3. Build per-player arbitrage signal
signal = {}
for sid, e in crosswalk.items():
    fp_id = e.get("fantasypros_id")
    if not fp_id:
        continue
    dyn_1qb = percentile("dynasty_1qb", fp_id)
    dyn_sf = percentile("dynasty_sf", fp_id)
    red_1qb = percentile("redraft_1qb", fp_id)
    red_sf = percentile("redraft_sf", fp_id)
    signal[sid] = {
        "dyn_pctile_1qb": dyn_1qb, "red_pctile_1qb": red_1qb,
        "gap_1qb": (dyn_1qb - red_1qb) if (dyn_1qb is not None and red_1qb is not None) else None,
        "dyn_pctile_sf": dyn_sf, "red_pctile_sf": red_sf,
        "gap_sf": (dyn_sf - red_sf) if (dyn_sf is not None and red_sf is not None) else None,
    }

with open("/home/claude/sleeper/arbitrage_signal.json", "w") as f:
    json.dump(signal, f)

matched = sum(1 for v in signal.values() if v["gap_1qb"] is not None or v["gap_sf"] is not None)
print(f"{len(signal)} players with fp_id, {matched} with a computable dynasty-vs-redraft gap")
