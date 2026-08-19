import csv, collections
from scipy.stats import fisher_exact

pts = {}
with open('/tmp/pfr/player_team_season.csv') as f:
    for row in csv.DictReader(f):
        pts[(row['player_id'], int(row['season']))] = row['team']

coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}

def base_tier(t):
    return t[:-1] if t.endswith('*') else t
SUPERSTAR_TIERS = {'Superstar', 'League Winner'}

player_seasons = []
with open('/tmp/pfr/all_rankings_tiered.csv') as f:
    for row in csv.DictReader(f):
        pos = row['position']
        if pos not in POS_ROLE:
            continue
        tier = base_tier(row['tier'])
        if tier == 'Uncategorized (<4 games)':
            continue
        season = int(row['season'])
        team = pts.get((row['player_id'], season))
        if team is None:
            continue
        player_seasons.append({
            'player_id': row['player_id'], 'display_name': row['display_name'], 'season': season,
            'position': pos, 'team': team, 'is_superstar': tier in SUPERSTAR_TIERS,
        })

# League baseline: per distinct player, did they EVER reach superstar tier (at that position)?
league_players = collections.defaultdict(lambda: collections.defaultdict(bool))  # position -> player_id -> ever_superstar
for r in player_seasons:
    league_players[r['position']][r['player_id']] = league_players[r['position']][r['player_id']] or r['is_superstar']

base_rate = {}
for pos, pdict in league_players.items():
    total = len(pdict)
    supers = sum(1 for v in pdict.values() if v)
    base_rate[pos] = (supers, total)
print('League base "ever reached superstar" rate by position (per distinct player):')
for pos, (b, t) in base_rate.items():
    print(f'  {pos}: {b}/{t} = {b/t:.1%}')

def credit_player_level(role_key_builder):
    # coach -> position -> player_id -> ever_superstar (under this coach)
    data = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in player_seasons:
        season, team, pos = r['season'], r['team'], r['position']
        role = role_key_builder(pos)
        names = coach_tbl.get((season, team, role), [])
        for name in names:
            pdict = data[name][pos]
            prev = pdict.get(r['player_id'], False)
            pdict[r['player_id']] = prev or r['is_superstar']
    return data

def report(data, filename, min_players=8):
    rows_out = []
    for name, pos_dict in data.items():
        for pos, pdict in pos_dict.items():
            total = len(pdict)
            if total < min_players:
                continue
            supers = sum(1 for v in pdict.values() if v)
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
        w.writerow(['coach_name', 'position', 'n_distinct_players', 'n_ever_superstar', 'superstar_player_rate', 'league_base_rate', 'p_value'])
        for row in rows_out:
            w.writerow(row)
    return rows_out

pos_data = credit_player_level(lambda pos: POS_ROLE[pos])
oc_data = credit_player_level(lambda pos: 'OC')
hc_data = credit_player_level(lambda pos: 'HC')

pos_out = report(pos_data, '/tmp/pfr/coach_effects/position_coach_superstar_playerlevel.csv', min_players=8)
oc_out = report(oc_data, '/tmp/pfr/coach_effects/oc_superstar_playerlevel.csv', min_players=8)
hc_out = report(hc_data, '/tmp/pfr/coach_effects/hc_superstar_playerlevel.csv', min_players=8)

for label, out in [('Position coaches', pos_out), ('OCs', oc_out), ('HCs', hc_out)]:
    n_tests = len(out)
    bonf = 0.05 / n_tests if n_tests else 1
    sig = [r for r in out if r[6] == r[6] and r[6] < 0.05]
    sig_bonf = [r for r in out if r[6] == r[6] and r[6] < bonf]
    print(f'\n{label}: {n_tests} tested (min 8 distinct players), {len(sig)} at p<0.05, Bonferroni thresh {bonf:.5f} -> {len(sig_bonf)} survive')
    for r in sig[:15]:
        print(' ', r)
