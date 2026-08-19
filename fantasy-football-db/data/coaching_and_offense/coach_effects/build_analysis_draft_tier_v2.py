import json, csv, collections, statistics
from scipy.stats import ttest_ind

player_seasons = json.load(open('/tmp/pfr/coach_effects/player_seasons_with_draft.json'))
baseline = json.load(open('/tmp/pfr/coach_effects/draft_tier_baseline.json'))

coach_tbl = collections.defaultdict(list)
with open('/tmp/pfr/coach_effects/coach_table.csv') as f:
    for row in csv.DictReader(f):
        coach_tbl[(int(row['season']), row['team'], row['role'])].append(row['coach_name'])

POS_ROLE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE'}

by_player = collections.defaultdict(list)
for p in player_seasons:
    by_player[(p['player_id'], p['position'])].append(p)

# Population: (pos, draft_tier) -> {player_id: avg_tier_score across whole career}
pop_dist = collections.defaultdict(dict)
for (pid, pos), seasons in by_player.items():
    dt = seasons[0]['draft_tier']
    if dt == 'Unknown':
        continue
    avg_score = sum(s['tier_score'] for s in seasons) / len(seasons)
    pop_dist[(pos, dt)][pid] = avg_score

def player_avg_under_coach(role_key_builder):
    data = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list))))
    for p in player_seasons:
        pos = p['position']
        dt = p['draft_tier']
        if dt == 'Unknown':
            continue
        role = role_key_builder(pos)
        names = coach_tbl.get((p['season'], p['team'], role), [])
        for name in names:
            data[name][pos][dt][p['player_id']].append(p['tier_score'])
    return data

def report(data, filename, min_players=15):
    rows_out = []
    for coach, pos_dict in data.items():
        for pos, dt_dict in pos_dict.items():
            for dt, players in dt_dict.items():
                n = len(players)
                if n < min_players:
                    continue
                coach_player_avgs = {pid: sum(v)/len(v) for pid, v in players.items()}
                coach_vals = list(coach_player_avgs.values())
                coach_mean = statistics.mean(coach_vals)
                # rest-of-population excluding this coach's own players (avoid self-comparison contamination)
                pop = pop_dist.get((pos, dt), {})
                rest_vals = [v for pid, v in pop.items() if pid not in coach_player_avgs]
                if len(rest_vals) < 5 or len(coach_vals) < 2 or statistics.pstdev(coach_vals) + statistics.pstdev(rest_vals) == 0:
                    p_val = float('nan')
                else:
                    try:
                        _, p_val = ttest_ind(coach_vals, rest_vals, equal_var=False)
                    except Exception:
                        p_val = float('nan')
                rest_mean = statistics.mean(rest_vals) if rest_vals else float('nan')
                rows_out.append((coach, pos, dt, n, round(coach_mean, 3), round(rest_mean, 3), round(coach_mean - rest_mean, 3), p_val))
    rows_out.sort(key=lambda x: (x[7] if x[7] == x[7] else 1))
    with open(filename, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['coach_name', 'position', 'draft_tier', 'n_distinct_players', 'coach_avg_tier_score',
                     'rest_of_league_avg_tier_score', 'overperformance', 'p_value'])
        for row in rows_out:
            w.writerow(row)
    return rows_out

pos_data = player_avg_under_coach(lambda pos: POS_ROLE[pos])
oc_data = player_avg_under_coach(lambda pos: 'OC')
hc_data = player_avg_under_coach(lambda pos: 'HC')

pos_out = report(pos_data, '/tmp/pfr/coach_effects/draft_tier_position_coach_v2.csv', min_players=15)
oc_out = report(oc_data, '/tmp/pfr/coach_effects/draft_tier_oc_v2.csv', min_players=15)
hc_out = report(hc_data, '/tmp/pfr/coach_effects/draft_tier_hc_v2.csv', min_players=15)

for label, out in [('Position coaches', pos_out), ('OCs', oc_out), ('HCs', hc_out)]:
    n_tests = len(out)
    bonf = 0.05 / n_tests if n_tests else 1
    sig = [r for r in out if r[7] == r[7] and r[7] < 0.05]
    sig_bonf = [r for r in out if r[7] == r[7] and r[7] < bonf]
    print(f'\n{label}: {n_tests} tested (min 15 players/bucket), {len(sig)} at p<0.05, Bonferroni {bonf:.5f} -> {len(sig_bonf)} survive')
    for r in sorted(sig, key=lambda x: -x[6])[:20]:
        print(' ', r)
