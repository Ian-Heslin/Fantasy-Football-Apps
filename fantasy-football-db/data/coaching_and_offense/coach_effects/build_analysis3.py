import csv, collections
from scipy.stats import fisher_exact

# Player-team-season lookup
pts = {}
with open('/tmp/pfr/player_team_season.csv') as f:
    for row in csv.DictReader(f):
        pts[(row['player_id'], int(row['season']))] = row['team']

coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}
SUPERSTAR_TIERS = {'Superstar', 'League Winner'}

def base_tier(t):
    return t[:-1] if t.endswith('*') else t

# Load all player-seasons with tier
player_seasons = []
with open('/tmp/pfr/all_rankings_tiered.csv') as f:
    for row in csv.DictReader(f):
        pos = row['position']
        if pos not in POS_ROLE:
            continue
        tier = base_tier(row['tier'])
        if tier == 'Uncategorized (<4 games)':
            continue  # too few games to mean anything
        season = int(row['season'])
        team = pts.get((row['player_id'], season))
        if team is None:
            continue
        player_seasons.append({
            'player_id': row['player_id'], 'season': season, 'position': pos,
            'team': team, 'is_superstar': tier in SUPERSTAR_TIERS,
        })

print('qualifying player-seasons with team resolved:', len(player_seasons))

base_rate = collections.defaultdict(lambda: [0, 0])
for r in player_seasons:
    base_rate[r['position']][1] += 1
    if r['is_superstar']:
        base_rate[r['position']][0] += 1
print('League base superstar-tier rates by position:')
for pos, (b, t) in base_rate.items():
    print(f'  {pos}: {b}/{t} = {b/t:.1%}')

def credit(role_key_builder):
    stats_by_coach = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in player_seasons:
        season, team, pos = r['season'], r['team'], r['position']
        role = role_key_builder(pos)
        names = coach_tbl.get((season, team, role), [])
        for name in names:
            stats_by_coach[name][pos][1] += 1
            if r['is_superstar']:
                stats_by_coach[name][pos][0] += 1
    return stats_by_coach

def report(stats_by_coach, filename, min_n=10):
    rows_out = []
    for name, pos_dict in stats_by_coach.items():
        for pos, (supers, total) in pos_dict.items():
            if total < min_n:
                continue
            base_b, base_t = base_rate[pos]
            table = [[supers, total - supers], [base_b - supers, (base_t - total) - (base_b - supers)]]
            try:
                _, p = fisher_exact(table)
            except Exception:
                p = float('nan')
            rate = supers / total
            base = base_b / base_t
            rows_out.append((name, pos, total, supers, rate, base, p))
    rows_out.sort(key=lambda x: (x[6] if x[6] == x[6] else 1))
    with open(filename, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['coach_name', 'position', 'n_player_seasons', 'n_superstar_seasons', 'superstar_rate', 'league_base_rate', 'p_value'])
        for row in rows_out:
            w.writerow(row)
    return rows_out

pos_stats = credit(lambda pos: POS_ROLE[pos])
oc_stats = credit(lambda pos: 'OC')
hc_stats = credit(lambda pos: 'HC')

pos_out = report(pos_stats, '/tmp/pfr/coach_effects/position_coach_superstar_stats.csv', min_n=15)
oc_out = report(oc_stats, '/tmp/pfr/coach_effects/oc_superstar_stats.csv', min_n=15)
hc_out = report(hc_stats, '/tmp/pfr/coach_effects/hc_superstar_stats.csv', min_n=15)

for label, out in [('Position coaches', pos_out), ('OCs', oc_out), ('HCs', hc_out)]:
    n_tests = len(out)
    sig = [r for r in out if r[6] == r[6] and r[6] < 0.05]
    bonf = 0.05 / n_tests if n_tests else 1
    sig_bonf = [r for r in out if r[6] == r[6] and r[6] < bonf]
    print(f'\n{label}: {n_tests} tested, {len(sig)} at p<0.05 (Bonferroni threshold {bonf:.5f}: {len(sig_bonf)} survive)')
    for r in sig[:15]:
        print(' ', r)
