import csv, collections, json
from scipy.stats import fisher_exact

breakout_rows = json.load(open('/tmp/pfr/coach_effects/breakout_rows.json'))
coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}

# League baseline at player level: of distinct (player, position) candidacies, did they EVER break out (any candidate season)?
league_players = collections.defaultdict(lambda: collections.defaultdict(bool))
for r in breakout_rows:
    key = r['player_id']
    league_players[r['position']][key] = league_players[r['position']][key] or r['broke_out']

base_rate = {}
for pos, pdict in league_players.items():
    total = len(pdict)
    b = sum(1 for v in pdict.values() if v)
    base_rate[pos] = (b, total)
print('League base "ever broke out" rate by position (per distinct candidate):')
for pos, (b, t) in base_rate.items():
    print(f'  {pos}: {b}/{t} = {b/t:.1%}')

def credit_player_level(role_key_builder):
    data = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in breakout_rows:
        season, team, pos = r['season_breakout'], r['next_team'], r['position']
        role = role_key_builder(pos)
        names = coach_tbl.get((season, team, role), [])
        for name in names:
            pdict = data[name][pos]
            prev = pdict.get(r['player_id'], False)
            pdict[r['player_id']] = prev or r['broke_out']
    return data

def report(data, filename, min_players=8):
    rows_out = []
    for name, pos_dict in data.items():
        for pos, pdict in pos_dict.items():
            total = len(pdict)
            if total < min_players:
                continue
            b = sum(1 for v in pdict.values() if v)
            base_b, base_t = base_rate[pos]
            table = [[b, total - b], [base_b - b, (base_t - total) - (base_b - b)]]
            try:
                _, p = fisher_exact(table)
            except Exception:
                p = float('nan')
            rate = b / total
            base = base_b / base_t
            rows_out.append((name, pos, total, b, rate, base, p))
    rows_out.sort(key=lambda x: (x[6] if x[6] == x[6] else 1))
    with open(filename, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['coach_name', 'position', 'n_distinct_candidates', 'n_ever_broke_out', 'breakout_player_rate', 'league_base_rate', 'p_value'])
        for row in rows_out:
            w.writerow(row)
    return rows_out

pos_data = credit_player_level(lambda pos: POS_ROLE[pos])
oc_data = credit_player_level(lambda pos: 'OC')
hc_data = credit_player_level(lambda pos: 'HC')

pos_out = report(pos_data, '/tmp/pfr/coach_effects/position_coach_breakout_playerlevel.csv', min_players=8)
oc_out = report(oc_data, '/tmp/pfr/coach_effects/oc_breakout_playerlevel.csv', min_players=8)
hc_out = report(hc_data, '/tmp/pfr/coach_effects/hc_breakout_playerlevel.csv', min_players=8)

for label, out in [('Position coaches', pos_out), ('OCs', oc_out), ('HCs', hc_out)]:
    n_tests = len(out)
    bonf = 0.05 / n_tests if n_tests else 1
    sig = [r for r in out if r[6] == r[6] and r[6] < 0.05]
    sig_bonf = [r for r in out if r[6] == r[6] and r[6] < bonf]
    print(f'\n{label}: {n_tests} tested (min 8 distinct candidates), {len(sig)} at p<0.05, Bonferroni thresh {bonf:.5f} -> {len(sig_bonf)} survive')
    for r in sig[:15]:
        print(' ', r)
