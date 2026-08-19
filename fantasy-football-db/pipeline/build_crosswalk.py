import csv, json

DP_DIR = "/home/claude/dynastyprocess-data/files"

# 1. Load id crosswalk (sleeper_id -> other ids/name)
crosswalk = {}
with open(f"{DP_DIR}/db_playerids.csv") as f:
    for row in csv.DictReader(f):
        sid = row["sleeper_id"]
        if sid and sid != "NA":
            crosswalk[sid] = {
                "sleeper_id": sid,
                "name": row["name"],
                "position": row["position"],
                "team": row["team"],
                "fantasypros_id": row["fantasypros_id"] if row["fantasypros_id"] != "NA" else None,
                "espn_id": row["espn_id"] if row["espn_id"] != "NA" else None,
                "yahoo_id": row["yahoo_id"] if row["yahoo_id"] != "NA" else None,
                "age": row["age"],
            }

# 2. Load dynasty trade values, index by fantasypros_id
values_by_fp = {}
with open(f"{DP_DIR}/values.csv") as f:
    for row in csv.DictReader(f):
        values_by_fp[row["fp_id"]] = {
            "value_1qb": row["value_1qb"],
            "value_2qb": row["value_2qb"],
            "ecr_1qb": row["ecr_1qb"],
            "ecr_2qb": row["ecr_2qb"],
            "ecr_pos": row["ecr_pos"],
            "scrape_date": row["scrape_date"],
        }

# 3. Merge values into crosswalk where possible
matched = 0
for sid, entry in crosswalk.items():
    fp = entry["fantasypros_id"]
    if fp and fp in values_by_fp:
        entry.update(values_by_fp[fp])
        matched += 1

print(f"Total sleeper_id entries: {len(crosswalk)}")
print(f"Matched to a dynasty value: {matched}")

with open("/home/claude/sleeper/player_crosswalk.json", "w") as f:
    json.dump(crosswalk, f)

print("Saved /home/claude/sleeper/player_crosswalk.json")
