import csv, collections
from scipy import stats

# --- Load player-team-season map ---
pts = {}  # (player_id, season) -> team
with open('/tmp/pfr/player_team_season.csv') as f:
    for row in csv.DictReader(f):
        pts[(row['player_id'], int(row['season']))] = row['team']

# --- Load coach table: (season, team, role) -> list of coach names ---
coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}

# =========================================================
# ANALYSIS A: Breakout rate by coach
# Candidate = season S row (below-Star), outcome = broke_out_next_year (season S+1)
# Attribute to the coach(es) of the player's ACTUAL team in season S+1
# =========================================================
breakout_rows = []
with open('/tmp/pfr/breakout_with_adp.csv') as f:
    for row in csv.DictReader(f):
        pos = row['position']
        if pos not in POS_ROLE:
            continue
        season = int(row['season'])
        pid = row['player_id']
        broke = row['broke_out_next_year'] == 'True'
        next_team = pts.get((pid, season + 1))
        if next_team is None:
            continue  # player not in league next season / no data
        breakout_rows.append({
            'player_id': pid, 'season_candidate': season, 'season_breakout': season + 1,
            'position': pos, 'next_team': next_team, 'broke_out': broke,
        })

print('breakout candidate rows with resolvable next-season team:', len(breakout_rows))

# Aggregate: for each coach role assignment, credit each candidate to all coaches in that role
# that season+team (position coach, OC, HC)
def credit(role_key_builder, label):
    stats_by_coach = collections.defaultdict(lambda: [0, 0])  # name -> [breakouts, total]
    for r in breakout_rows:
        season, team, pos = r['season_breakout'], r['next_team'], r['position']
        role = role_key_builder(pos)
        names = coach_tbl.get((season, team, role), [])
        for name in names:
            stats_by_coach[name][1] += 1
            if r['broke_out']:
                stats_by_coach[name][0] += 1
    return stats_by_coach

pos_coach_stats = credit(lambda pos: POS_ROLE[pos], 'position coach')
oc_stats = credit(lambda pos: 'OC', 'OC')
hc_stats = credit(lambda pos: 'HC', 'HC')

# league base rate per position (for comparison)
base_rate = collections.defaultdict(lambda: [0, 0])
for r in breakout_rows:
    base_rate[r['position']][1] += 1
    if r['broke_out']:
        base_rate[r['position']][0] += 1
print('League base breakout rates (by position):')
for pos, (b, t) in base_rate.items():
    print(f'  {pos}: {b}/{t} = {b/t:.1%}')

def write_coach_report(stats_by_coach, filename, min_n=10):
    out = []
    for name, (breakouts, total) in stats_by_coach.items():
        if total < min_n:
            continue
        rate = breakouts / total
        out.append((name, total, breakouts, rate))
    out.sort(key=lambda x: -x[3])
    with open(filename, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['coach_name', 'n_candidates', 'n_breakouts', 'breakout_rate'])
        for row in out:
            w.writerow(row)
    return out

pos_out = write_coach_report(pos_coach_stats, '/tmp/pfr/coach_effects/position_coach_breakout_rates.csv')
oc_out = write_coach_report(oc_stats, '/tmp/pfr/coach_effects/oc_breakout_rates.csv')
hc_out = write_coach_report(hc_stats, '/tmp/pfr/coach_effects/hc_breakout_rates.csv')

print(f'\nPosition coaches with n>=10 candidates: {len(pos_out)}')
print(f'OCs with n>=10 candidates: {len(oc_out)}')
print(f'HCs with n>=10 candidates: {len(hc_out)}')

# Save breakout_rows for reuse
import json
with open('/tmp/pfr/coach_effects/breakout_rows.json', 'w') as f:
    json.dump(breakout_rows, f)
